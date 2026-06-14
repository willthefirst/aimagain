"""Tests for the ``Location`` wire value object and its helpers (#451).

Covers:
- :class:`Location` rejects unknown subkeys (``extra="forbid"``),
  unknown US-state values, malformed ZIP codes, and missing required
  subfields.
- :class:`LocationPartial` accepts each subfield independently and
  treats an empty partial (every subfield ``None``) as "no patch"
  via the at-least-one-field rule on embedding Update schemas.
- :func:`gather_flat_location` rolls flat ``location_<sub>`` keys on a
  dict into the nested block, leaves unrelated ``location_*`` keys
  (any hypothetical sibling field on client-referral
  schemas) alone, and attaches a transient ``location`` attribute to
  attribute-bag inputs that expose only the flat columns.
- :func:`flatten_location_on_dump` inverts the nested → flat
  projection on ``model_dump``.
- :class:`Location.state` literal stays in lockstep with
  ``US_STATES`` — the post-#451 home for the location-state guardrail
  that used to live on each embedding schema.
"""

from types import SimpleNamespace
from typing import get_args

import pytest
from pydantic import ValidationError

from src.domain.logic.value_objects.location import (
    Location,
    LocationPartial,
    flatten_location_on_dump,
    gather_flat_location,
)
from src.domain.models.enums import US_STATES

# --- Location (required-state flavor) -----------------------------------


def test_location_accepts_valid_triple():
    loc = Location(city="Boise", state="ID", zip="83702")
    assert loc.city == "Boise"
    assert loc.state == "ID"
    assert loc.zip == "83702"


def test_location_strips_city_whitespace():
    loc = Location(city="  Boise  ", state="ID", zip="83702")
    assert loc.city == "Boise"


def test_location_rejects_empty_city():
    with pytest.raises(ValidationError):
        Location(city="   ", state="ID", zip="83702")


def test_location_rejects_unknown_state():
    with pytest.raises(ValidationError):
        Location(city="Boise", state="ZZ", zip="83702")


def test_location_rejects_non_5_digit_zip():
    with pytest.raises(ValidationError):
        Location(city="Boise", state="ID", zip="1234")
    with pytest.raises(ValidationError):
        Location(city="Boise", state="ID", zip="abcde")


def test_location_rejects_missing_field():
    """All three subfields are required on the Create/Read flavor."""
    with pytest.raises(ValidationError):
        Location(city="Boise", state="ID")  # zip missing


def test_location_rejects_unknown_subkey():
    """`extra="forbid"` on the value object stops an attacker from
    smuggling fields through a top-level schema by hiding them inside
    a nested ``location`` block."""
    with pytest.raises(ValidationError):
        Location.model_validate(
            {"city": "Boise", "state": "ID", "zip": "83702", "country": "US"}
        )


def test_location_equality_via_round_trip():
    a = Location(city="Boise", state="ID", zip="83702")
    b = Location.model_validate(a.model_dump())
    assert a == b


def test_location_state_literal_matches_us_states_tuple():
    """:class:`Location.state` is the post-#451 home for the
    location-state lockstep guardrail. The Literal values must match
    ``US_STATES`` exactly — drift here would let clinician /
    client-referral schemas accept a state value the DB CHECK
    constraint would reject."""
    annotation = Location.model_fields["state"].annotation
    assert set(get_args(annotation)) == set(US_STATES)


# --- LocationPartial (Update flavor) ------------------------------------


def test_location_partial_accepts_each_subfield_independently():
    just_city = LocationPartial(city="Boise")
    assert just_city.city == "Boise"
    assert just_city.state is None
    assert just_city.zip is None

    just_state = LocationPartial(state="ID")
    assert just_state.state == "ID"
    assert just_state.city is None


def test_location_partial_default_is_all_none():
    """An empty partial — every subfield ``None`` — is the in-Python
    representation of "no patch to location". The embedding Update
    schema's at-least-one-field rule treats this as unset (see
    :func:`src.framework.schema_validators._field_is_set`)."""
    p = LocationPartial()
    assert p.city is None and p.state is None and p.zip is None


def test_location_partial_rejects_invalid_state():
    with pytest.raises(ValidationError):
        LocationPartial(state="ZZ")


def test_location_partial_rejects_invalid_zip():
    with pytest.raises(ValidationError):
        LocationPartial(zip="abc")


def test_location_partial_state_literal_matches_us_states_tuple():
    """Same lockstep guard as :func:`test_location_state_literal_matches_us_states_tuple`
    but on the partial-update flavor — the literal lives inside
    ``T | None`` so we pull the inner arm explicitly."""
    annotation = LocationPartial.model_fields["state"].annotation
    args = get_args(annotation)
    literal_arm = next(get_args(arm) for arm in args if get_args(arm))
    assert set(literal_arm) == set(US_STATES)


# --- gather_flat_location ----------------------------------------------


def test_gather_flat_location_rolls_three_flat_keys_into_nested():
    data = {
        "location_city": "Boise",
        "location_state": "ID",
        "location_zip": "83702",
        "other": 1,
    }
    out = gather_flat_location(data)
    assert out == {
        "location": {"city": "Boise", "state": "ID", "zip": "83702"},
        "other": 1,
    }


def test_gather_flat_location_handles_partial_flat_keys():
    """Update payloads can supply just one location subfield (e.g.
    ``location_city`` alone). Missing subkeys stay absent from the
    nested dict so ``LocationPartial`` defaults the rest to ``None``."""
    out = gather_flat_location({"location_city": "Boise", "other": 1})
    assert out == {"location": {"city": "Boise"}, "other": 1}


def test_gather_flat_location_leaves_other_location_prefixed_keys_alone():
    """The helper consumes only the ``location_city`` / ``location_state``
    / ``location_zip`` triple. Any other key sharing the ``location_``
    prefix (a hypothetical future or sibling field) must pass through
    unchanged — the helper isn't pattern-matching on the prefix."""
    out = gather_flat_location(
        {
            "location_city": "Boise",
            "location_state": "ID",
            "location_zip": "83702",
            "location_notes": "near the park",
        }
    )
    assert out["location"] == {"city": "Boise", "state": "ID", "zip": "83702"}
    assert out["location_notes"] == "near the park"


def test_gather_flat_location_passthrough_when_no_flat_keys():
    """A dict that already uses the nested shape (or just doesn't
    touch location) passes through unchanged."""
    data = {"location": {"city": "Boise", "state": "ID", "zip": "83702"}}
    assert gather_flat_location(data) is data
    assert gather_flat_location({"other": 1}) == {"other": 1}


def test_gather_flat_location_merges_flat_into_existing_nested():
    """If a payload sends both nested and flat (a contract violation
    in practice), flat values are merged into the nested dict. The
    embedding schema's ``Location`` then rejects the conflict via
    ``extra="forbid"`` on duplicate subkeys."""
    out = gather_flat_location(
        {
            "location": {"city": "Boise"},
            "location_state": "ID",
        }
    )
    assert out["location"] == {"city": "Boise", "state": "ID"}


def test_gather_flat_location_handles_simplenamespace_attrs():
    """Attribute-bag inputs (SimpleNamespace, SQLAlchemy rows that
    pre-date :class:`LocationMixin`, etc.) get a transient
    ``location`` attribute attached so Pydantic's per-field
    ``from_attributes`` look-up finds the value object."""
    bag = SimpleNamespace(
        location_city="Boise",
        location_state="ID",
        location_zip="83702",
        practice_name="Sunrise",
    )
    out = gather_flat_location(bag)
    assert out is bag
    assert out.location == {"city": "Boise", "state": "ID", "zip": "83702"}


def test_gather_flat_location_skips_attribute_bag_with_location_already():
    """A SQLAlchemy row that already exposes ``location`` (via
    :class:`LocationMixin`'s ``@property``) skips the attach-transient
    path — its ``location`` attribute is read directly."""
    bag = SimpleNamespace(
        location={"city": "X", "state": "ID", "zip": "83702"},
        location_city="ignored",
    )
    out = gather_flat_location(bag)
    assert out.location == {"city": "X", "state": "ID", "zip": "83702"}


# --- flatten_location_on_dump ------------------------------------------


def test_flatten_location_on_dump_unrolls_nested_to_flat():
    """Inverse of :func:`gather_flat_location`. Used inside the
    embedding schema's ``@model_serializer`` to keep the wire/JSON/
    audit shape flat post-#451."""
    payload = Location(city="Boise", state="ID", zip="83702")
    out = flatten_location_on_dump(
        payload, {"location": {"city": "Boise", "state": "ID", "zip": "83702"}}
    )
    assert out == {
        "location_city": "Boise",
        "location_state": "ID",
        "location_zip": "83702",
    }
    assert "location" not in out


def test_flatten_location_on_dump_emits_only_present_subfields():
    """Partial-update dumps (``exclude_unset=True``) hand the helper
    a nested block containing only the touched subfields; absent ones
    must not appear in the output (otherwise patches would write
    ``location_state=None`` over a persisted value)."""
    payload = LocationPartial(city="Boise")
    out = flatten_location_on_dump(payload, {"location": {"city": "Boise"}})
    assert out == {"location_city": "Boise"}


def test_flatten_location_on_dump_no_location_block_is_noop():
    """When the schema's serializer dump has no ``location`` key
    (e.g. ``exclude_unset=True`` on an Update that didn't touch
    location), the helper leaves the dict alone."""
    payload = LocationPartial()
    out = flatten_location_on_dump(payload, {"description": "x"})
    assert out == {"description": "x"}
