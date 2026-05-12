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
    ClientReferralCreate,
    ClientReferralRead,
    ClientReferralUpdate,
    ProviderAvailabilityCreate,
    ProviderAvailabilityRead,
    ProviderAvailabilityUpdate,
    post_audit_snapshot,
    post_create_adapter,
    post_update_adapter,
)
from src.domain.models.enums import (
    CLIENT_AGE_GROUP_LABELS,
    CLIENT_AGE_GROUPS,
    CLIENT_REFERRAL_SERVICE_LABELS,
    CLIENT_REFERRAL_SERVICES,
    DESIRED_TIME_SLOT_LABELS,
    DESIRED_TIME_SLOTS,
    INSURANCE_LABELS,
    INSURANCE_OPTIONS,
    LANGUAGE_LABELS,
    LANGUAGES,
    LOCATION_AVAILABILITY_LABELS,
    LOCATION_AVAILABILITY_OPTIONS,
    US_STATES,
)
from tests.helpers import client_referral_payload, provider_availability_payload

# --- PostCreate (discriminated union) -----------------------------------


def test_post_create_dispatches_client_referral():
    payload = client_referral_payload(description="needs a clinician")
    p = post_create_adapter.validate_python(payload)
    assert isinstance(p, ClientReferralCreate)
    assert p.kind == "client_referral"
    assert p.description == "needs a clinician"
    assert p.location_city == "Springfield"
    assert p.location_state == "IL"
    assert p.insurance == "in_network"


def test_post_create_requires_kind():
    """`kind` is required — no default fallback."""
    payload = client_referral_payload()
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


def test_post_create_strips_surrounding_whitespace_client_referral():
    p = post_create_adapter.validate_python(
        client_referral_payload(description="  help  ", location_city="  Boise  ")
    )
    assert p.description == "help"
    assert p.location_city == "Boise"


def test_post_create_client_referral_rejects_empty_description():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(client_referral_payload(description="   "))


@pytest.mark.parametrize(
    "missing_field",
    [
        "location_city",
        "location_state",
        "location_zip",
        "location_in_person",
        "location_virtual",
        "client_dem_age_groups",
        "description",
        "insurance",
    ],
)
def test_post_create_client_referral_requires_all_required_fields(missing_field):
    payload = client_referral_payload()
    payload.pop(missing_field)
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(payload)


def test_post_create_client_referral_optional_fields_default_none():
    p = post_create_adapter.validate_python(client_referral_payload())
    assert p.services_psychotherapy_modality is None


def test_post_create_client_referral_default_languages():
    """`languages` defaults to ['en'] — keeps "submit with defaults" valid
    even though the field is required min-1 (#428)."""
    payload = client_referral_payload()
    payload.pop("languages")
    p = post_create_adapter.validate_python(payload)
    assert p.languages == ["en"]


def test_post_create_client_referral_accepts_multiple_languages():
    p = post_create_adapter.validate_python(
        client_referral_payload(languages=["en", "es"])
    )
    assert p.languages == ["en", "es"]


def test_post_create_client_referral_rejects_empty_languages():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(client_referral_payload(languages=[]))


def test_post_create_client_referral_rejects_unknown_language_token():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(client_referral_payload(languages=["xx"]))


def test_post_create_client_referral_accepts_multiple_age_groups():
    """CR's `client_dem_age_groups` accepts a multi-bucket list (#432) —
    the original single-valued `client_dem_ages` forced referrers to
    pick one when a child straddled buckets."""
    p = post_create_adapter.validate_python(
        client_referral_payload(
            client_dem_age_groups=["children_6_10", "preteens_11_13"]
        )
    )
    assert p.client_dem_age_groups == ["children_6_10", "preteens_11_13"]


def test_post_create_client_referral_rejects_empty_age_groups():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            client_referral_payload(client_dem_age_groups=[])
        )


def test_post_create_client_referral_strips_optional_to_none():
    p = post_create_adapter.validate_python(
        client_referral_payload(services_psychotherapy_modality="   ")
    )
    assert p.services_psychotherapy_modality is None


def test_post_create_client_referral_rejects_invalid_zip():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(client_referral_payload(location_zip="abc"))
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            client_referral_payload(location_zip="1234")
        )


def test_post_create_client_referral_rejects_unknown_state():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            client_referral_payload(location_state="ZZ")
        )


def test_post_create_client_referral_rejects_unknown_age_group():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            client_referral_payload(client_dem_age_groups=["too_old"])
        )


def test_post_create_client_referral_rejects_unknown_insurance():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            client_referral_payload(insurance="cash_only")
        )


def test_post_create_rejects_owner_id():
    """owner_id is server-managed; clients sending it must be rejected."""
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            client_referral_payload(owner_id=str(uuid.uuid4()))
        )


def test_post_create_rejects_unknown_fields_on_client_referral():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(client_referral_payload(evil=True))


# --- PostUpdate (discriminated union) -----------------------------------


def test_post_update_client_referral_accepts_description():
    p = post_update_adapter.validate_python(
        {"kind": "client_referral", "description": "fresh"}
    )
    assert isinstance(p, ClientReferralUpdate)
    assert p.description == "fresh"


def test_post_update_client_referral_accepts_partial_other_field():
    """Any one editable field is enough for a partial update."""
    p = post_update_adapter.validate_python(
        {"kind": "client_referral", "location_city": "Boise"}
    )
    assert isinstance(p, ClientReferralUpdate)
    assert p.location_city == "Boise"
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


def test_post_update_strips_whitespace_client_referral():
    p = post_update_adapter.validate_python(
        {"kind": "client_referral", "description": "  hi  "}
    )
    assert p.description == "hi"


def test_post_update_client_referral_requires_at_least_one_field():
    """An empty PATCH (just `kind`) must 422."""
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python({"kind": "client_referral"})


def test_post_update_client_referral_explicit_nulls_only_is_rejected():
    """All editable fields explicitly null still counts as no-op → 422."""
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "client_referral", "description": None, "location_city": None}
        )


def test_post_update_client_referral_rejects_whitespace_only_description():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "client_referral", "description": "   "}
        )


def test_post_update_client_referral_rejects_invalid_zip():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "client_referral", "location_zip": "12"}
        )


def test_post_update_client_referral_rejects_owner_id():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {
                "kind": "client_referral",
                "description": "d",
                "owner_id": str(uuid.uuid4()),
            }
        )


def test_post_update_client_referral_rejects_unknown_field():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "client_referral", "description": "d", "evil": True}
        )


# --- post_audit_snapshot ------------------------------------------------


def test_audit_snapshot_for_client_referral_post():
    owner_id = uuid.uuid4()
    detail_attrs = client_referral_payload()
    detail_attrs.pop("kind")
    post = SimpleNamespace(
        kind="client_referral",
        owner_id=owner_id,
        client_referral_detail=SimpleNamespace(**detail_attrs),
    )
    snap = post_audit_snapshot(post)
    assert snap["kind"] == "client_referral"
    assert snap["owner_id"] == str(owner_id)
    assert snap["description"] == detail_attrs["description"]
    assert snap["location_city"] == detail_attrs["location_city"]
    assert snap["insurance"] == detail_attrs["insurance"]


def test_audit_snapshot_unknown_kind_raises():
    """An unregistered kind fails the discriminator union — the audit
    helper surfaces it as a `ValidationError` (subclass of `ValueError`),
    not a silent partial snapshot."""
    post = SimpleNamespace(
        kind="not_a_kind",
        owner_id=uuid.uuid4(),
        client_referral_detail=None,
        provider_availability_detail=None,
    )
    with pytest.raises(ValidationError):
        post_audit_snapshot(post)


# --- provider_availability variants -------------------------------------


def test_post_create_dispatches_provider_availability():
    p = post_create_adapter.validate_python(
        provider_availability_payload(practice_name="Acme Health")
    )
    assert isinstance(p, ProviderAvailabilityCreate)
    assert p.kind == "provider_availability"
    assert p.practice_name == "Acme Health"
    assert p.sliding_scale is False


@pytest.mark.parametrize(
    "token",
    ["group_therapy", "family_therapy", "couples_therapy"],
)
def test_post_create_provider_availability_accepts_new_services_tokens(token):
    """The three service tokens added in #440 validate on PA Create."""
    p = post_create_adapter.validate_python(
        provider_availability_payload(services=[token])
    )
    assert p.services == [token]


def test_post_create_provider_availability_accepts_schedule_text():
    """`schedule_text` is the free-text companion to `desired_times` for
    cohort dates / fixed program hours (#442)."""
    p = post_create_adapter.validate_python(
        provider_availability_payload(schedule_text="M-F 9am-5pm, starts May 11")
    )
    assert p.schedule_text == "M-F 9am-5pm, starts May 11"


def test_post_create_provider_availability_schedule_text_strips_whitespace():
    p = post_create_adapter.validate_python(
        provider_availability_payload(schedule_text="   ")
    )
    assert p.schedule_text is None


def test_post_update_provider_availability_accepts_schedule_text_only():
    p = post_update_adapter.validate_python(
        {"kind": "provider_availability", "schedule_text": "New cohort starts Jun 1"}
    )
    assert p.schedule_text == "New cohort starts Jun 1"


def test_post_create_provider_availability_accepts_day_program_setting():
    """`day_program` setting added in #440 for program-style posts."""
    p = post_create_adapter.validate_python(
        provider_availability_payload(settings=["day_program"])
    )
    assert p.settings == ["day_program"]


@pytest.mark.parametrize(
    "token",
    ["group_therapy", "family_therapy", "couples_therapy"],
)
def test_post_create_client_referral_accepts_new_services_tokens(token):
    """CR shares the `CLIENT_REFERRAL_SERVICES` vocab with PA; widening
    propagates to both (#440)."""
    p = post_create_adapter.validate_python(client_referral_payload(services=[token]))
    assert p.services == [token]


@pytest.mark.parametrize(
    "token",
    [
        "in_network",
        "out_of_network",
        "in_and_out_of_network",
        "self_pay_only",
        "please_contact",
    ],
)
def test_post_create_provider_availability_accepts_all_insurance_tokens(token):
    """All five `INSURANCE_OPTIONS` tokens validate after #438's vocab
    widening (`self_pay_only`, `please_contact` were added)."""
    p = post_create_adapter.validate_python(
        provider_availability_payload(payment_situation=token)
    )
    assert p.payment_situation == token


@pytest.mark.parametrize(
    "token",
    [
        "in_network",
        "out_of_network",
        "in_and_out_of_network",
        "self_pay_only",
        "please_contact",
    ],
)
def test_post_create_client_referral_accepts_all_insurance_tokens(token):
    """CR's `insurance` shares the `INSURANCE_OPTIONS` vocab with PA;
    widening propagates to both."""
    p = post_create_adapter.validate_python(client_referral_payload(insurance=token))
    assert p.insurance == token


def test_post_create_provider_availability_default_languages():
    """`languages` defaults to ['en'] — keeps the submit-with-defaults case
    valid even though the field is required min-1 (#425)."""
    payload = provider_availability_payload()
    payload.pop("languages")
    p = post_create_adapter.validate_python(payload)
    assert p.languages == ["en"]


def test_post_create_provider_availability_accepts_multiple_languages():
    p = post_create_adapter.validate_python(
        provider_availability_payload(languages=["en", "es"])
    )
    assert p.languages == ["en", "es"]


def test_post_create_provider_availability_rejects_empty_languages():
    """`languages` is required min-1; an empty list 422s, mirroring services."""
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(provider_availability_payload(languages=[]))


def test_post_create_provider_availability_rejects_unknown_language_token():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            provider_availability_payload(languages=["xx"])
        )


def test_post_create_provider_availability_accepts_multiple_age_groups():
    """`age_groups` accepts a multi-bucket list — Katie Reeves spans 3
    buckets, that's the whole point of #430."""
    p = post_create_adapter.validate_python(
        provider_availability_payload(
            age_groups=["adolescents_14_18", "young_adults_19_24", "adults_25_64"]
        )
    )
    assert p.age_groups == [
        "adolescents_14_18",
        "young_adults_19_24",
        "adults_25_64",
    ]


def test_post_create_provider_availability_rejects_empty_age_groups():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            provider_availability_payload(age_groups=[])
        )


def test_post_create_provider_availability_rejects_unknown_age_group_token():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            provider_availability_payload(age_groups=["not_a_bucket"])
        )


def test_post_update_provider_availability_accepts_age_groups_only():
    p = post_update_adapter.validate_python(
        {
            "kind": "provider_availability",
            "age_groups": ["young_adults_19_24", "adults_25_64"],
        }
    )
    assert p.age_groups == ["young_adults_19_24", "adults_25_64"]


def test_post_create_strips_surrounding_whitespace_provider_availability():
    p = post_create_adapter.validate_python(
        provider_availability_payload(practice_name="  Acme  ")
    )
    assert p.practice_name == "Acme"


def test_post_create_provider_availability_rejects_empty_practice_name():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            provider_availability_payload(practice_name="   ")
        )


@pytest.mark.parametrize(
    "missing_field",
    [
        "practice_name",
        "available_providers",
        "location_state",
        "client_focus",
        "age_groups",
        "payment_situation",
        "sliding_scale",
    ],
)
def test_post_create_provider_availability_requires_required_fields(missing_field):
    payload = provider_availability_payload()
    payload.pop(missing_field)
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(payload)


def test_post_create_rejects_unknown_fields_on_provider_availability():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(provider_availability_payload(evil=True))


def test_post_create_rejects_cross_kind_field_bleed():
    """Cross-kind field bleed must not validate. `client_dem_age_groups`
    is a client-referral-only field; it has no place in a PA payload."""
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            provider_availability_payload(client_dem_age_groups=["adults_25_64"])
        )


def test_post_create_provider_availability_accepts_free_text_fields():
    """`description`, `referral_instructions`, `website` round-trip through
    the Create schema."""
    p = post_create_adapter.validate_python(
        provider_availability_payload(
            description="Lead narrative pitch.",
            referral_instructions="Email the intake coordinator.",
            website="example.com",
        )
    )
    assert p.description == "Lead narrative pitch."
    assert p.referral_instructions == "Email the intake coordinator."
    assert p.website == "example.com"


def test_post_create_provider_availability_free_text_fields_default_none():
    """All three new fields are optional; absent → None."""
    payload = provider_availability_payload()
    for field in ("description", "referral_instructions", "website"):
        payload.pop(field, None)
    p = post_create_adapter.validate_python(payload)
    assert p.description is None
    assert p.referral_instructions is None
    assert p.website is None


def test_post_create_provider_availability_strips_free_text_whitespace():
    p = post_create_adapter.validate_python(
        provider_availability_payload(
            description="  trim me  ",
            referral_instructions="   ",
        )
    )
    assert p.description == "trim me"
    # Whitespace-only collapses to None per StrippedOptionalText.
    assert p.referral_instructions is None


def test_post_update_provider_availability_accepts_description_only():
    """A PATCH that only sets `description` is a valid partial update."""
    p = post_update_adapter.validate_python(
        {"kind": "provider_availability", "description": "Updated pitch."}
    )
    assert p.description == "Updated pitch."


def test_post_update_provider_availability_accepts_practice_name():
    p = post_update_adapter.validate_python(
        {"kind": "provider_availability", "practice_name": "Renamed"}
    )
    assert isinstance(p, ProviderAvailabilityUpdate)
    assert p.practice_name == "Renamed"


def test_post_update_provider_availability_accepts_sliding_scale_only():
    p = post_update_adapter.validate_python(
        {"kind": "provider_availability", "sliding_scale": True}
    )
    assert isinstance(p, ProviderAvailabilityUpdate)
    assert p.sliding_scale is True


def test_post_update_provider_availability_strips_whitespace():
    p = post_update_adapter.validate_python(
        {"kind": "provider_availability", "practice_name": "  Renamed  "}
    )
    assert p.practice_name == "Renamed"


def test_post_update_provider_availability_requires_at_least_one_field():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python({"kind": "provider_availability"})


def test_post_update_provider_availability_rejects_whitespace_only():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "provider_availability", "practice_name": "   "}
        )


def test_post_update_provider_availability_rejects_unknown_field():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {
                "kind": "provider_availability",
                "practice_name": "Acme",
                "evil": True,
            }
        )


def test_audit_snapshot_for_provider_availability_post():
    """Snapshotting a `kind='provider_availability'` post flattens through
    `provider_availability_detail`."""
    owner_id = uuid.uuid4()
    detail_attrs = provider_availability_payload()
    detail_attrs.pop("kind")
    post = SimpleNamespace(
        kind="provider_availability",
        owner_id=owner_id,
        client_referral_detail=None,
        provider_availability_detail=SimpleNamespace(**detail_attrs),
    )
    snap = post_audit_snapshot(post)
    assert snap["kind"] == "provider_availability"
    assert snap["owner_id"] == str(owner_id)
    assert snap["practice_name"] == detail_attrs["practice_name"]
    assert snap["sliding_scale"] is False
    assert snap["cost"] is None


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
        # Read variants
        (ClientReferralRead, "location_state", US_STATES),
        (ClientReferralRead, "location_in_person", LOCATION_AVAILABILITY_OPTIONS),
        (ClientReferralRead, "location_virtual", LOCATION_AVAILABILITY_OPTIONS),
        (ClientReferralRead, "insurance", INSURANCE_OPTIONS),
        (ProviderAvailabilityRead, "location_state", US_STATES),
        (ProviderAvailabilityRead, "in_person_sessions", LOCATION_AVAILABILITY_OPTIONS),
        (ProviderAvailabilityRead, "virtual_sessions", LOCATION_AVAILABILITY_OPTIONS),
        (ProviderAvailabilityRead, "payment_situation", INSURANCE_OPTIONS),
        # Create variants
        (ClientReferralCreate, "location_state", US_STATES),
        (ClientReferralCreate, "insurance", INSURANCE_OPTIONS),
        (ProviderAvailabilityCreate, "payment_situation", INSURANCE_OPTIONS),
        # Update variants (Optional[Literal[*TUPLE]])
        (ClientReferralUpdate, "location_state", US_STATES),
        (ClientReferralUpdate, "insurance", INSURANCE_OPTIONS),
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
        (client_referral_payload, "client_referral"),
        (provider_availability_payload, "provider_availability"),
    ],
)
def test_post_create_desired_times_defaults_to_empty_list(payload_factory, kind):
    payload = payload_factory()
    payload.pop("desired_times", None)
    p = post_create_adapter.validate_python(payload)
    assert p.desired_times == []


@pytest.mark.parametrize(
    "payload_factory",
    [client_referral_payload, provider_availability_payload],
)
def test_post_create_desired_times_accepts_subset(payload_factory):
    p = post_create_adapter.validate_python(
        payload_factory(desired_times=["monday_morning", "friday_evening"])
    )
    assert p.desired_times == ["monday_morning", "friday_evening"]


@pytest.mark.parametrize(
    "payload_factory",
    [client_referral_payload, provider_availability_payload],
)
def test_post_create_desired_times_coerces_scalar_to_singleton_list(payload_factory):
    """htmx's `json-enc` collapses a 1-checkbox-checked group to a scalar
    string on the wire (only emits an array when the same name appears
    2+ times). The schema's `_scalar_to_list` BeforeValidator wraps that
    scalar back into a list before the `Literal[*TUPLE]` member check
    fires; otherwise users who pick exactly one slot would 422."""
    p = post_create_adapter.validate_python(
        payload_factory(desired_times="monday_morning")
    )
    assert p.desired_times == ["monday_morning"]


@pytest.mark.parametrize("kind", ["client_referral", "provider_availability"])
def test_post_update_desired_times_coerces_scalar_to_singleton_list(kind):
    p = post_update_adapter.validate_python(
        {"kind": kind, "desired_times": "monday_morning"}
    )
    assert p.desired_times == ["monday_morning"]


@pytest.mark.parametrize(
    "payload_factory",
    [client_referral_payload, provider_availability_payload],
)
def test_post_create_desired_times_rejects_unknown_token(payload_factory):
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            payload_factory(desired_times=["monday_brunch"])
        )


@pytest.mark.parametrize(
    "kind",
    ["client_referral", "provider_availability"],
)
def test_post_update_desired_times_replaces_with_explicit_list(kind):
    """Sending an explicit list (including `[]`) replaces the persisted
    selection. None is "leave unchanged" — that's the standard
    `update_post` semantic, not specific to this field."""
    p = post_update_adapter.validate_python(
        {"kind": kind, "desired_times": ["monday_morning"]}
    )
    assert p.desired_times == ["monday_morning"]
    p = post_update_adapter.validate_python({"kind": kind, "desired_times": []})
    assert p.desired_times == []


@pytest.mark.parametrize(
    "kind",
    ["client_referral", "provider_availability"],
)
def test_post_update_desired_times_rejects_unknown_token(kind):
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": kind, "desired_times": ["monday_brunch"]}
        )


# --- services multi-select ----------------------------------------------
#
# Same shape as `desired_times` (scalar coercion + Literal vocabulary) on
# both kinds, plus a min-1 invariant on `provider_availability` that the
# `RequiredServicesField` annotation enforces on Create and Update.


def test_post_create_client_referral_services_defaults_to_empty_list():
    """CR's `services` is optional with `[]` default — omitting it is fine."""
    payload = client_referral_payload()
    payload.pop("services", None)
    p = post_create_adapter.validate_python(payload)
    assert p.services == []


@pytest.mark.parametrize(
    "payload_factory",
    [client_referral_payload, provider_availability_payload],
)
def test_post_create_services_accepts_subset(payload_factory):
    p = post_create_adapter.validate_python(
        payload_factory(services=["evaluation", "psychotherapy"])
    )
    assert p.services == ["evaluation", "psychotherapy"]


@pytest.mark.parametrize(
    "payload_factory",
    [client_referral_payload, provider_availability_payload],
)
def test_post_create_services_coerces_scalar_to_singleton_list(payload_factory):
    """Same json-enc 1-checkbox-collapses-to-scalar story as `desired_times`
    — the shared `_scalar_to_list` BeforeValidator handles it."""
    p = post_create_adapter.validate_python(payload_factory(services="evaluation"))
    assert p.services == ["evaluation"]


@pytest.mark.parametrize(
    "payload_factory",
    [client_referral_payload, provider_availability_payload],
)
def test_post_create_services_rejects_unknown_token(payload_factory):
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(payload_factory(services=["telekinesis"]))


def test_post_create_provider_availability_services_accepts_empty_list():
    """PA's `services` was required-min-1; #433 relaxed to optional. An
    explicit `[]` validates."""
    p = post_create_adapter.validate_python(provider_availability_payload(services=[]))
    assert p.services == []


def test_post_create_provider_availability_services_absent_defaults_empty():
    """Omitting `services` entirely on PA falls back to `[]` per #433."""
    payload = provider_availability_payload()
    payload.pop("services")
    p = post_create_adapter.validate_python(payload)
    assert p.services == []


def test_post_create_provider_availability_accepts_omitted_optional_fields():
    """City, ZIP, sessions, services, settings are all optional after
    #433 — telehealth-only and venue-based posts must be expressible."""
    payload = provider_availability_payload()
    for field in (
        "location_city",
        "location_zip",
        "in_person_sessions",
        "virtual_sessions",
        "services",
        "settings",
    ):
        payload.pop(field, None)
    p = post_create_adapter.validate_python(payload)
    assert p.location_city is None
    assert p.location_zip is None
    assert p.in_person_sessions is None
    assert p.virtual_sessions is None
    assert p.services == []
    assert p.settings == []


@pytest.mark.parametrize(
    "kind",
    ["client_referral", "provider_availability"],
)
def test_post_update_services_coerces_scalar_to_singleton_list(kind):
    p = post_update_adapter.validate_python({"kind": kind, "services": "evaluation"})
    assert p.services == ["evaluation"]


def test_post_update_client_referral_services_accepts_empty_list():
    """CR's `services` is optional, so PATCHing `services: []` clears the
    selection — same semantics as `desired_times`."""
    p = post_update_adapter.validate_python({"kind": "client_referral", "services": []})
    assert p.services == []


def test_post_update_provider_availability_services_rejects_empty_list():
    """PA preserves the min-1 invariant on PATCH: explicit `[]` 422s; `None`
    (leave-unchanged) is the supported way to not mutate the field."""
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "provider_availability", "services": []}
        )


def test_post_update_provider_availability_services_accepts_non_empty_list():
    p = post_update_adapter.validate_python(
        {"kind": "provider_availability", "services": ["psychotherapy"]}
    )
    assert p.services == ["psychotherapy"]


@pytest.mark.parametrize(
    "kind",
    ["client_referral", "provider_availability"],
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
        (LANGUAGES, LANGUAGE_LABELS),
        (INSURANCE_OPTIONS, INSURANCE_LABELS),
        (DESIRED_TIME_SLOTS, DESIRED_TIME_SLOT_LABELS),
        (CLIENT_REFERRAL_SERVICES, CLIENT_REFERRAL_SERVICE_LABELS),
    ],
)
def test_labels_cover_their_tuples(values, labels):
    """Each `*_LABELS` dict in `src/domain/models/enums.py` must have a
    label for every value in its corresponding tuple. The form-render
    macro looks labels up by value; an unmapped value would render with
    a `KeyError` at request time. Catching it here keeps the failure
    mode loud and offline."""
    assert set(labels) == set(values)
