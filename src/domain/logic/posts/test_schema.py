"""Tests for the post wire schemas.

Covers:
- The kind-discriminated union accepts each kind's payload and rejects
  unknown / missing `kind` values.
- Per-kind validation: non-empty stripping, ZIP regex, controlled
  vocabularies, partial-update at-least-one rule, server-managed-field
  rejection, unknown-field rejection.
- `post_audit_snapshot` projects a SQLAlchemy `Post` of any registered
  kind through the right snapshot class.
- `test_schema_literals_match_model_tuples` guards that the
  `Literal[*TUPLE]` types here stay aligned with the source-of-truth
  tuples in `src/domain/models/enums.py`.
- `test_labels_cover_their_tuples` guards that every value in a
  `*_OPTIONS`/`*_GROUPS` tuple has an entry in its sibling
  `*_LABELS` dict (consumed by the form-render macro).
"""

import uuid
from types import SimpleNamespace
from typing import get_args

import pytest
from pydantic import ValidationError

from src.domain.logic.posts.schema import (
    OpeningCreate,
    OpeningUpdate,
    ReferralCreate,
    ReferralRead,
    ReferralUpdate,
    post_audit_snapshot,
    post_create_adapter,
    post_update_adapter,
)
from src.domain.models.enums import (
    CLIENT_AGE_GROUP_ICONS,
    CLIENT_AGE_GROUP_LABELS,
    CLIENT_AGE_GROUP_LABELS_SINGULAR,
    CLIENT_AGE_GROUPS,
    CLIENT_AGE_GROUPS_BY_KEY,
    DESIRED_TIME_SLOT_LABELS,
    DESIRED_TIME_SLOTS,
    GENDER_LABELS,
    GENDERS,
    INSURANCE_CARRIER_LABELS,
    INSURANCE_CARRIERS,
    INSURANCE_POSTURE_ICONS,
    INSURANCE_POSTURE_LABELS,
    INSURANCE_POSTURES,
    LANGUAGE_LABELS,
    LANGUAGES,
    LOCATION_AVAILABILITY_LABELS,
    LOCATION_AVAILABILITY_OPTIONS,
    NETWORK_PREFERENCE_LABELS,
    NETWORK_PREFERENCES,
    REFERRAL_SERVICE_ICONS,
    REFERRAL_SERVICE_LABELS,
    REFERRAL_SERVICES,
    TREATMENT_SETTINGS,
    TREATMENT_SETTINGS_ICONS,
)
from tests.helpers import opening_payload, referral_payload

# --- PostCreate (discriminated union) -----------------------------------


def test_post_create_dispatches_referral():
    payload = referral_payload(description="needs a clinician")
    p = post_create_adapter.validate_python(payload)
    assert isinstance(p, ReferralCreate)
    assert p.kind == "referral"
    assert p.description == "needs a clinician"
    # Post-#451: ``(city, state, zip)`` live on the embedded
    # :class:`Location` value object. The form/JSON wire shape stays
    # flat — see ``test_post_create_referral_dump_keeps_flat_location``.
    assert p.location.city == "Springfield"
    assert p.location.state == "IL"
    assert p.network_preference == "in_network_required"
    assert p.insurance_carrier is None


def test_post_create_requires_kind():
    """`kind` is required — no default fallback."""
    payload = referral_payload()
    payload.pop("kind")
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(payload)


def test_post_create_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python({"kind": "unknown", "x": 1})


def test_post_create_rejects_retired_note_kind():
    """The `note` kind was removed; payloads sending it must 422."""
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            {"kind": "note", "title": "hi", "body": "there"}
        )


def test_post_create_strips_surrounding_whitespace_referral():
    p = post_create_adapter.validate_python(
        referral_payload(description="  help  ", location_city="  Boise  ")
    )
    assert p.description == "help"
    assert p.location.city == "Boise"


def test_post_create_referral_rejects_empty_description():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(referral_payload(description="   "))


@pytest.mark.parametrize(
    "missing_field",
    [
        "location_city",
        "location_state",
        "location_zip",
        "location_in_person",
        "location_virtual",
        "age_groups",
        "description",
        "network_preference",
    ],
)
def test_post_create_referral_requires_all_required_fields(missing_field):
    payload = referral_payload()
    payload.pop(missing_field)
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(payload)


def test_post_create_referral_optional_fields_default_none():
    p = post_create_adapter.validate_python(referral_payload())
    assert p.treatment_modality is None


def test_post_create_referral_default_languages():
    """`languages` defaults to ['en'] — keeps "submit with defaults" valid
    even though the field is required min-1 (#428)."""
    payload = referral_payload()
    payload.pop("languages")
    p = post_create_adapter.validate_python(payload)
    assert p.languages == ["en"]


def test_post_create_referral_accepts_multiple_languages():
    p = post_create_adapter.validate_python(referral_payload(languages=["en", "es"]))
    assert p.languages == ["en", "es"]


def test_post_create_referral_rejects_empty_languages():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(referral_payload(languages=[]))


def test_post_create_referral_rejects_unknown_language_token():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(referral_payload(languages=["xx"]))


def test_post_create_referral_accepts_multiple_age_groups():
    """CR's `age_groups` accepts a multi-bucket list (#432) —
    the original single-valued `client_dem_ages` forced referrers to
    pick one when a child straddled buckets."""
    p = post_create_adapter.validate_python(
        referral_payload(age_groups=["children_6_10", "preteens_11_13"])
    )
    assert p.age_groups == ["children_6_10", "preteens_11_13"]


def test_post_create_referral_rejects_empty_age_groups():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(referral_payload(age_groups=[]))


def test_post_create_referral_strips_optional_to_none():
    p = post_create_adapter.validate_python(referral_payload(treatment_modality="   "))
    assert p.treatment_modality is None


def test_post_create_referral_rejects_invalid_zip():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(referral_payload(location_zip="abc"))
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(referral_payload(location_zip="1234"))


def test_post_create_referral_rejects_unknown_state():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(referral_payload(location_state="ZZ"))


def test_post_create_referral_rejects_unknown_age_group():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(referral_payload(age_groups=["too_old"]))


def test_post_create_referral_rejects_unknown_network_preference():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            referral_payload(network_preference="bring_cash")
        )


def test_post_create_referral_rejects_unknown_insurance_carrier():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            referral_payload(insurance_carrier="my_local_co_op")
        )


def test_post_create_referral_allows_null_insurance_carrier():
    """Carrier is nullable — self-pay / unknown / no carrier all map to
    NULL on the wire. The form hides the field when network_preference
    = no_preference; the schema accepts a null carrier with any
    network_preference value."""
    for pref in NETWORK_PREFERENCES:
        p = post_create_adapter.validate_python(
            referral_payload(network_preference=pref, insurance_carrier=None)
        )
        assert p.network_preference == pref
        assert p.insurance_carrier is None


def test_post_create_referral_accepts_carrier_with_required():
    p = post_create_adapter.validate_python(
        referral_payload(
            network_preference="in_network_required",
            insurance_carrier="cigna",
        )
    )
    assert p.network_preference == "in_network_required"
    assert p.insurance_carrier == "cigna"


def test_post_create_rejects_owner_id():
    """owner_id is server-managed; clients sending it must be rejected."""
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            referral_payload(owner_id=str(uuid.uuid4()))
        )


def test_post_create_rejects_unknown_fields_on_referral():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(referral_payload(evil=True))


# --- PostUpdate (discriminated union) -----------------------------------


def test_post_update_referral_accepts_description():
    p = post_update_adapter.validate_python(
        {"kind": "referral", "description": "fresh"}
    )
    assert isinstance(p, ReferralUpdate)
    assert p.description == "fresh"


def test_post_update_referral_accepts_partial_other_field():
    """Any one editable field is enough for a partial update. After
    #451, ``location_city`` arrives flat and rolls into the nested
    ``location: LocationPartial`` field; ``description`` stays absent
    on this patch."""
    p = post_update_adapter.validate_python(
        {"kind": "referral", "location_city": "Boise"}
    )
    assert isinstance(p, ReferralUpdate)
    assert p.location is not None
    assert p.location.city == "Boise"
    assert p.description is None


def test_post_update_requires_kind():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python({"description": "x"})


def test_post_update_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python({"kind": "unknown", "x": 1})


def test_post_update_rejects_retired_note_kind():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python({"kind": "note", "title": "x"})


def test_post_update_strips_whitespace_referral():
    p = post_update_adapter.validate_python(
        {"kind": "referral", "description": "  hi  "}
    )
    assert p.description == "hi"


def test_post_update_referral_requires_at_least_one_field():
    """An empty PATCH (just `kind`) must 422."""
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python({"kind": "referral"})


def test_post_update_referral_explicit_nulls_only_is_rejected():
    """All editable fields explicitly null still counts as no-op → 422."""
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "referral", "description": None, "location_city": None}
        )


def test_post_update_referral_rejects_whitespace_only_description():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python({"kind": "referral", "description": "   "})


def test_post_update_referral_rejects_invalid_zip():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python({"kind": "referral", "location_zip": "12"})


def test_post_update_referral_rejects_owner_id():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {
                "kind": "referral",
                "description": "d",
                "owner_id": str(uuid.uuid4()),
            }
        )


def test_post_update_referral_rejects_unknown_field():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "referral", "description": "d", "evil": True}
        )


# --- post_audit_snapshot ------------------------------------------------


def test_audit_snapshot_for_referral_post():
    owner_id = uuid.uuid4()
    detail_attrs = referral_payload()
    detail_attrs.pop("kind")
    post = SimpleNamespace(
        kind="referral",
        owner_id=owner_id,
        referral_detail=SimpleNamespace(**detail_attrs),
    )
    snap = post_audit_snapshot(post)
    assert snap["kind"] == "referral"
    assert snap["owner_id"] == str(owner_id)
    assert snap["description"] == detail_attrs["description"]
    assert snap["location_city"] == detail_attrs["location_city"]
    assert snap["network_preference"] == detail_attrs["network_preference"]
    assert snap["insurance_carrier"] == detail_attrs["insurance_carrier"]


def test_audit_snapshot_unknown_kind_raises():
    """An unregistered kind fails the discriminator union — the audit
    helper surfaces it as a `ValidationError` (subclass of `ValueError`),
    not a silent partial snapshot."""
    post = SimpleNamespace(
        kind="not_a_kind",
        owner_id=uuid.uuid4(),
        referral_detail=None,
        opening_detail=None,
    )
    with pytest.raises(ValidationError):
        post_audit_snapshot(post)


# --- opening variants -------------------------------------


def test_post_create_dispatches_opening():
    p = post_create_adapter.validate_python(opening_payload())
    assert isinstance(p, OpeningCreate)
    assert p.kind == "opening"
    # Insurance posture moved to Provider in #449; PA no longer carries
    # `sliding_scale` / `payment_situation` / `cost` on the wire.


@pytest.mark.parametrize(
    "token",
    ["group_therapy", "family_therapy", "couples_therapy"],
)
def test_post_create_opening_accepts_new_services_tokens(token):
    """The three service tokens added in #440 validate on PA Create."""
    p = post_create_adapter.validate_python(opening_payload(services=[token]))
    assert p.services == [token]


def test_post_create_opening_accepts_schedule_text():
    """`schedule_text` is the free-text companion to `desired_times` for
    cohort dates / fixed program hours (#442)."""
    p = post_create_adapter.validate_python(
        opening_payload(schedule_text="M-F 9am-5pm, starts May 11")
    )
    assert p.schedule_text == "M-F 9am-5pm, starts May 11"


def test_post_create_opening_schedule_text_strips_whitespace():
    p = post_create_adapter.validate_python(opening_payload(schedule_text="   "))
    assert p.schedule_text is None


def test_post_update_opening_accepts_schedule_text_only():
    p = post_update_adapter.validate_python(
        {"kind": "opening", "schedule_text": "New cohort starts Jun 1"}
    )
    assert p.schedule_text == "New cohort starts Jun 1"


def test_post_create_opening_accepts_day_program_setting():
    """`day_program` setting added in #440 for program-style posts."""
    p = post_create_adapter.validate_python(opening_payload(settings=["day_program"]))
    assert p.settings == ["day_program"]


@pytest.mark.parametrize(
    "token",
    ["group_therapy", "family_therapy", "couples_therapy"],
)
def test_post_create_referral_accepts_new_services_tokens(token):
    """CR shares the `REFERRAL_SERVICES` vocab with PA; widening
    propagates to both (#440)."""
    p = post_create_adapter.validate_python(referral_payload(services=[token]))
    assert p.services == [token]


@pytest.mark.parametrize("token", NETWORK_PREFERENCES)
def test_post_create_referral_accepts_all_network_preference_tokens(token):
    """Every `NETWORK_PREFERENCES` token validates as a CR
    `network_preference` value."""
    p = post_create_adapter.validate_python(referral_payload(network_preference=token))
    assert p.network_preference == token


@pytest.mark.parametrize("token", INSURANCE_CARRIERS)
def test_post_create_referral_accepts_all_insurance_carriers(token):
    """Every `INSURANCE_CARRIERS` token validates as a CR
    `insurance_carrier` value (shared vocab with Provider)."""
    p = post_create_adapter.validate_python(referral_payload(insurance_carrier=token))
    assert p.insurance_carrier == token


def test_post_create_referral_rejects_retired_in_network_token():
    """The old `insurance` enum is gone. A payload sending the legacy
    field gets ignored as an unknown field (extra='forbid' on
    WirePayload), so this 422s."""
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(referral_payload(insurance="in_network"))


def test_post_create_opening_default_languages():
    """`languages` defaults to ['en'] — keeps the submit-with-defaults case
    valid even though the field is required min-1 (#425)."""
    payload = opening_payload()
    payload.pop("languages")
    p = post_create_adapter.validate_python(payload)
    assert p.languages == ["en"]


def test_post_create_opening_accepts_multiple_languages():
    p = post_create_adapter.validate_python(opening_payload(languages=["en", "es"]))
    assert p.languages == ["en", "es"]


def test_post_create_opening_rejects_empty_languages():
    """`languages` is required min-1; an empty list 422s, mirroring services."""
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(opening_payload(languages=[]))


def test_post_create_opening_rejects_unknown_language_token():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(opening_payload(languages=["xx"]))


def test_post_create_opening_accepts_multiple_age_groups():
    """`age_groups` accepts a multi-bucket list — Katie Reeves spans 3
    buckets, that's the whole point of #430."""
    p = post_create_adapter.validate_python(
        opening_payload(
            age_groups=["adolescents_14_18", "young_adults_19_24", "adults_25_64"]
        )
    )
    assert p.age_groups == [
        "adolescents_14_18",
        "young_adults_19_24",
        "adults_25_64",
    ]


def test_post_create_opening_rejects_empty_age_groups():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(opening_payload(age_groups=[]))


def test_post_create_opening_rejects_unknown_age_group_token():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            opening_payload(age_groups=["not_a_bucket"])
        )


def test_post_update_opening_accepts_age_groups_only():
    p = post_update_adapter.validate_python(
        {
            "kind": "opening",
            "age_groups": ["young_adults_19_24", "adults_25_64"],
        }
    )
    assert p.age_groups == ["young_adults_19_24", "adults_25_64"]


@pytest.mark.parametrize(
    "missing_field",
    [
        "provider_id",
        "age_groups",
    ],
)
def test_post_create_opening_requires_required_fields(missing_field):
    payload = opening_payload()
    payload.pop(missing_field)
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(payload)


def test_post_create_rejects_unknown_fields_on_opening():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(opening_payload(evil=True))


def test_post_create_rejects_cross_kind_field_bleed():
    """Cross-kind field bleed must not validate. `location_in_person`
    is a client-referral-only field; it has no place in a PA payload."""
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(opening_payload(location_in_person="yes"))


def test_post_create_opening_accepts_free_text_fields():
    """`description`, `referral_instructions`, `website` round-trip through
    the Create schema."""
    p = post_create_adapter.validate_python(
        opening_payload(
            description="Lead narrative pitch.",
            referral_instructions="Email the intake coordinator.",
            website="example.com",
        )
    )
    assert p.description == "Lead narrative pitch."
    assert p.referral_instructions == "Email the intake coordinator."
    assert p.website == "example.com"


def test_post_create_opening_free_text_fields_default_none():
    """All three new fields are optional; absent → None."""
    payload = opening_payload()
    for field in ("description", "referral_instructions", "website"):
        payload.pop(field, None)
    p = post_create_adapter.validate_python(payload)
    assert p.description is None
    assert p.referral_instructions is None
    assert p.website is None


def test_post_create_opening_strips_free_text_whitespace():
    p = post_create_adapter.validate_python(
        opening_payload(
            description="  trim me  ",
            referral_instructions="   ",
        )
    )
    assert p.description == "trim me"
    # Whitespace-only collapses to None per StrippedOptionalText.
    assert p.referral_instructions is None


def test_post_update_opening_accepts_description_only():
    """A PATCH that only sets `description` is a valid partial update."""
    p = post_update_adapter.validate_python(
        {"kind": "opening", "description": "Updated pitch."}
    )
    assert p.description == "Updated pitch."


def test_post_update_opening_accepts_provider_id_only():
    """A PATCH that only repoints `provider_id` is a valid partial update.
    Replaces the pre-#449 `sliding_scale`-only test, since insurance posture
    now lives on Provider."""
    new_provider_id = uuid.uuid4()
    p = post_update_adapter.validate_python(
        {"kind": "opening", "provider_id": str(new_provider_id)}
    )
    assert isinstance(p, OpeningUpdate)
    assert p.provider_id == new_provider_id


def test_post_update_opening_strips_whitespace():
    """`description` is a free-text PA field — whitespace stripping still
    applies. (Practice-name stripping moved to Provider with #448.)"""
    p = post_update_adapter.validate_python(
        {"kind": "opening", "description": "  Renamed  "}
    )
    assert p.description == "Renamed"


def test_post_update_opening_requires_at_least_one_field():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python({"kind": "opening"})


def test_post_update_opening_rejects_whitespace_only():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python({"kind": "opening", "description": "   "})


def test_post_update_opening_rejects_unknown_field():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {
                "kind": "opening",
                "description": "Acme",
                "evil": True,
            }
        )


def test_audit_snapshot_for_opening_post():
    """Snapshotting a `kind='opening'` post flattens through
    `opening_detail`."""
    owner_id = uuid.uuid4()
    detail_attrs = opening_payload()
    detail_attrs.pop("kind")
    post = SimpleNamespace(
        kind="opening",
        owner_id=owner_id,
        referral_detail=None,
        opening_detail=SimpleNamespace(**detail_attrs),
    )
    snap = post_audit_snapshot(post)
    assert snap["kind"] == "opening"
    assert snap["owner_id"] == str(owner_id)
    # Per #448, the audit row records the FK to the Provider, not the
    # dereferenced practice fields. Practice-name/location/sessions live
    # on Provider now (and insurance posture / sliding-scale / cost live
    # there as of #449) — snapshotted via that entity's audit path.
    assert snap["provider_id"] == detail_attrs["provider_id"]
    assert "sliding_scale" not in snap
    assert "payment_situation" not in snap
    assert "cost" not in snap


# --- Schema-literal vs model-tuple guardrail ----------------------------


def _literal_args(model_cls, field_name: str) -> tuple[str, ...]:
    """Pull the `Literal[...]` accepted values off a Pydantic field's
    annotation, regardless of `Optional` wrapping."""
    annotation = model_cls.model_fields[field_name].annotation
    args = get_args(annotation)
    if args:
        # Optional[...] / Union[...]: find the Literal arm.
        for arm in args:
            literal_values = get_args(arm)
            if literal_values and all(isinstance(v, str) for v in literal_values):
                return literal_values
        # Direct Literal[...]
        if all(isinstance(a, str) for a in args):
            return args
    return ()


@pytest.mark.parametrize(
    "model_cls,field,expected",
    [
        # Read variants. ``location_state`` moved into the
        # :class:`Location` value object in #451 — see the lockstep
        # test in ``src/domain/logic/value_objects/test_location.py``.
        (ReferralRead, "location_in_person", LOCATION_AVAILABILITY_OPTIONS),
        (ReferralRead, "location_virtual", LOCATION_AVAILABILITY_OPTIONS),
        (ReferralRead, "network_preference", NETWORK_PREFERENCES),
        (ReferralRead, "insurance_carrier", INSURANCE_CARRIERS),
        (ReferralRead, "gender", GENDERS),
        # Create variants
        (ReferralCreate, "network_preference", NETWORK_PREFERENCES),
        (ReferralCreate, "insurance_carrier", INSURANCE_CARRIERS),
        (ReferralCreate, "gender", GENDERS),
        # Update variants (Optional[Literal[*TUPLE]])
        (ReferralUpdate, "network_preference", NETWORK_PREFERENCES),
        (ReferralUpdate, "insurance_carrier", INSURANCE_CARRIERS),
        (ReferralUpdate, "gender", GENDERS),
    ],
)
def test_schema_literals_match_model_tuples(model_cls, field, expected):
    """Schema `Literal[*TUPLE]`s and DB CHECK universes must agree,
    sourced from the tuples in `src/domain/models/enums.py`. If you add or
    rename a vocabulary value, update both places (and the migration);
    this guardrail keeps them honest."""
    assert set(_literal_args(model_cls, field)) == set(expected)


# --- desired_times multi-select -----------------------------------------


@pytest.mark.parametrize(
    "payload_factory,kind",
    [
        (referral_payload, "referral"),
        (opening_payload, "opening"),
    ],
)
def test_post_create_desired_times_defaults_to_empty_list(payload_factory, kind):
    payload = payload_factory()
    payload.pop("desired_times", None)
    p = post_create_adapter.validate_python(payload)
    assert p.desired_times == []


@pytest.mark.parametrize(
    "payload_factory",
    [referral_payload, opening_payload],
)
def test_post_create_desired_times_accepts_subset(payload_factory):
    p = post_create_adapter.validate_python(
        payload_factory(desired_times=["monday_am", "friday_pm"])
    )
    assert p.desired_times == ["monday_am", "friday_pm"]


@pytest.mark.parametrize(
    "payload_factory",
    [referral_payload, opening_payload],
)
def test_post_create_desired_times_coerces_scalar_to_singleton_list(payload_factory):
    """htmx's `json-enc` collapses a 1-checkbox-checked group to a scalar
    string on the wire (only emits an array when the same name appears
    2+ times). The schema's `_scalar_to_list` BeforeValidator wraps that
    scalar back into a list before the `Literal[*TUPLE]` member check
    fires; otherwise users who pick exactly one slot would 422."""
    p = post_create_adapter.validate_python(payload_factory(desired_times="monday_am"))
    assert p.desired_times == ["monday_am"]


@pytest.mark.parametrize("kind", ["referral", "opening"])
def test_post_update_desired_times_coerces_scalar_to_singleton_list(kind):
    p = post_update_adapter.validate_python(
        {"kind": kind, "desired_times": "monday_am"}
    )
    assert p.desired_times == ["monday_am"]


@pytest.mark.parametrize(
    "payload_factory",
    [referral_payload, opening_payload],
)
def test_post_create_desired_times_rejects_unknown_token(payload_factory):
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            payload_factory(desired_times=["monday_brunch"])
        )


@pytest.mark.parametrize(
    "kind",
    ["referral", "opening"],
)
def test_post_update_desired_times_replaces_with_explicit_list(kind):
    """Sending an explicit list (including `[]`) replaces the persisted
    selection. None is "leave unchanged" — that's the standard
    `update_post` semantic, not specific to this field."""
    p = post_update_adapter.validate_python(
        {"kind": kind, "desired_times": ["monday_am"]}
    )
    assert p.desired_times == ["monday_am"]
    p = post_update_adapter.validate_python({"kind": kind, "desired_times": []})
    assert p.desired_times == []


@pytest.mark.parametrize(
    "kind",
    ["referral", "opening"],
)
def test_post_update_desired_times_rejects_unknown_token(kind):
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": kind, "desired_times": ["monday_brunch"]}
        )


# --- services multi-select ----------------------------------------------
#
# Same shape as `desired_times` (scalar coercion + Literal vocabulary) on
# both kinds, plus a min-1 invariant on `opening` that the
# `RequiredServicesField` annotation enforces on Create and Update.


def test_post_create_referral_services_defaults_to_empty_list():
    """CR's `services` is optional with `[]` default — omitting it is fine."""
    payload = referral_payload()
    payload.pop("services", None)
    p = post_create_adapter.validate_python(payload)
    assert p.services == []


@pytest.mark.parametrize(
    "payload_factory",
    [referral_payload, opening_payload],
)
def test_post_create_services_accepts_subset(payload_factory):
    p = post_create_adapter.validate_python(
        payload_factory(services=["evaluation", "psychotherapy"])
    )
    assert p.services == ["evaluation", "psychotherapy"]


@pytest.mark.parametrize(
    "payload_factory",
    [referral_payload, opening_payload],
)
def test_post_create_services_coerces_scalar_to_singleton_list(payload_factory):
    """Same json-enc 1-checkbox-collapses-to-scalar story as `desired_times`
    — the shared `_scalar_to_list` BeforeValidator handles it."""
    p = post_create_adapter.validate_python(payload_factory(services="evaluation"))
    assert p.services == ["evaluation"]


@pytest.mark.parametrize(
    "payload_factory",
    [referral_payload, opening_payload],
)
def test_post_create_services_rejects_unknown_token(payload_factory):
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(payload_factory(services=["telekinesis"]))


def test_post_create_opening_services_accepts_empty_list():
    """PA's `services` was required-min-1; #433 relaxed to optional. An
    explicit `[]` validates."""
    p = post_create_adapter.validate_python(opening_payload(services=[]))
    assert p.services == []


def test_post_create_opening_services_absent_defaults_empty():
    """Omitting `services` entirely on PA falls back to `[]` per #433."""
    payload = opening_payload()
    payload.pop("services")
    p = post_create_adapter.validate_python(payload)
    assert p.services == []


def test_post_create_opening_accepts_omitted_optional_fields():
    """`services` and `settings` are optional on PA Create (#433) — omitting
    them defaults to `[]`. (Practice/location/session fields moved to
    Provider per #448 and are no longer wire fields on PA.)"""
    payload = opening_payload()
    for field in ("services", "settings"):
        payload.pop(field, None)
    p = post_create_adapter.validate_python(payload)
    assert p.services == []
    assert p.settings == []


@pytest.mark.parametrize(
    "kind",
    ["referral", "opening"],
)
def test_post_update_services_coerces_scalar_to_singleton_list(kind):
    p = post_update_adapter.validate_python({"kind": kind, "services": "evaluation"})
    assert p.services == ["evaluation"]


def test_post_update_referral_services_accepts_empty_list():
    """CR's `services` is optional, so PATCHing `services: []` clears the
    selection — same semantics as `desired_times`."""
    p = post_update_adapter.validate_python({"kind": "referral", "services": []})
    assert p.services == []


def test_post_update_opening_services_rejects_empty_list():
    """PA preserves the min-1 invariant on PATCH: explicit `[]` 422s; `None`
    (leave-unchanged) is the supported way to not mutate the field."""
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python({"kind": "opening", "services": []})


def test_post_update_opening_services_accepts_non_empty_list():
    p = post_update_adapter.validate_python(
        {"kind": "opening", "services": ["psychotherapy"]}
    )
    assert p.services == ["psychotherapy"]


@pytest.mark.parametrize(
    "kind",
    ["referral", "opening"],
)
def test_post_update_services_rejects_unknown_token(kind):
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python({"kind": kind, "services": ["telekinesis"]})


# --- Display labels cover their value tuples ----------------------------


@pytest.mark.parametrize(
    "values,labels",
    [
        (LOCATION_AVAILABILITY_OPTIONS, LOCATION_AVAILABILITY_LABELS),
        (CLIENT_AGE_GROUPS, CLIENT_AGE_GROUP_LABELS),
        (CLIENT_AGE_GROUPS, CLIENT_AGE_GROUP_LABELS_SINGULAR),
        (CLIENT_AGE_GROUPS, CLIENT_AGE_GROUPS_BY_KEY),
        (LANGUAGES, LANGUAGE_LABELS),
        (NETWORK_PREFERENCES, NETWORK_PREFERENCE_LABELS),
        (INSURANCE_CARRIERS, INSURANCE_CARRIER_LABELS),
        (DESIRED_TIME_SLOTS, DESIRED_TIME_SLOT_LABELS),
        (REFERRAL_SERVICES, REFERRAL_SERVICE_LABELS),
        (GENDERS, GENDER_LABELS),
    ],
)
def test_labels_cover_their_tuples(values, labels):
    """Each `*_LABELS` dict in `src/domain/models/enums.py` must have a
    label for every value in its corresponding tuple. The form-render
    macro looks labels up by value; an unmapped value would render with
    a `KeyError` at request time. Catching it here keeps the failure
    mode loud and offline."""
    assert set(labels) == set(values)


# --- Listing-row icons cover their value tuples -------------------------


@pytest.mark.parametrize(
    "values,icons",
    [
        (CLIENT_AGE_GROUPS, CLIENT_AGE_GROUP_ICONS),
        (REFERRAL_SERVICES, REFERRAL_SERVICE_ICONS),
        (TREATMENT_SETTINGS, TREATMENT_SETTINGS_ICONS),
        (INSURANCE_POSTURES, INSURANCE_POSTURE_ICONS),
        (INSURANCE_POSTURES, INSURANCE_POSTURE_LABELS),
    ],
)
def test_icons_cover_their_tuples(values, icons):
    """Each `*_ICONS` dict in `src/domain/models/enums.py` must have an
    icon name for every value in its corresponding tuple. The row macro
    (`src/domain/templates/posts/_item.html`) looks icons up by value;
    a missing key would render as `<i class="icon-">` (no glyph) at
    request time. Catching it here keeps the failure mode loud and
    offline — same pattern as `test_labels_cover_their_tuples` above."""
    assert set(icons) == set(values)
