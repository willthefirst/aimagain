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
    ClinicianOpeningCreate,
    ClinicianOpeningUpdate,
    ReferralCreate,
    ReferralRead,
    ReferralUpdate,
    post_audit_snapshot,
    post_create_adapter,
    post_update_adapter,
)
from src.domain.models.enums import (
    GENDERS,
    INSURANCE_CARRIERS,
    LOCATION_AVAILABILITY_OPTIONS,
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
    # Payment-paths (#1358 PR-e): defaults to in-network only per the
    # test helper, with no carriers picked yet.
    assert p.accepts_in_network is True
    assert p.accepts_out_of_network_superbill is False
    assert p.accepts_private_pay is False
    assert p.insurance_carriers == []


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
        # The picker submits this; `referring_clinician_id` is now
        # server-derived from it, so the affiliation id is the required
        # wire field, not the clinician id.
        "clinician_affiliation_id",
    ],
)
def test_post_create_referral_requires_all_required_fields(missing_field):
    payload = referral_payload()
    payload.pop(missing_field)
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(payload)


def test_post_create_referral_accepts_referring_clinician_id():
    """`referring_clinician_id` round-trips as a UUID on Create."""
    import uuid

    cid = uuid.uuid4()
    p = post_create_adapter.validate_python(
        referral_payload(referring_clinician_id=str(cid))
    )
    assert isinstance(p, ReferralCreate)
    assert p.referring_clinician_id == cid


def test_post_update_referral_accepts_referring_clinician_id_only():
    """`referring_clinician_id` alone is a valid partial update."""
    import uuid

    cid = uuid.uuid4()
    p = post_update_adapter.validate_python(
        {"kind": "referral", "referring_clinician_id": str(cid)}
    )
    assert isinstance(p, ReferralUpdate)
    assert p.referring_clinician_id == cid


def test_post_update_referral_referring_clinician_id_optional():
    """`referring_clinician_id` omitted on PATCH is None (leave unchanged)."""
    p = post_update_adapter.validate_python(
        {"kind": "referral", "description": "updated"}
    )
    assert isinstance(p, ReferralUpdate)
    assert p.referring_clinician_id is None


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


def test_post_create_referral_defaults_affirming_identities_to_empty_list():
    """`affirming_identities` is optional on the wire; empty list is
    the default (no preference stated)."""
    payload = referral_payload()
    payload.pop("affirming_identities", None)
    p = post_create_adapter.validate_python(payload)
    assert p.affirming_identities == []


def test_post_create_referral_accepts_affirming_identities_list():
    p = post_create_adapter.validate_python(
        referral_payload(affirming_identities=["lgbtq", "neurodiversity"])
    )
    assert p.affirming_identities == ["lgbtq", "neurodiversity"]


def test_post_create_referral_coerces_scalar_affirming_identity_to_list():
    """HTML form checkbox single-value submits land as a bare string;
    `scalar_to_list` normalizes to a one-element list before the
    `Literal[*AFFIRMING_IDENTITIES]` per-member check."""
    p = post_create_adapter.validate_python(
        referral_payload(affirming_identities="trans")
    )
    assert p.affirming_identities == ["trans"]


def test_post_create_referral_rejects_unknown_affirming_identity():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            referral_payload(affirming_identities=["not_a_real_token"])
        )


def test_post_create_referral_defaults_acceptable_license_types_to_empty_list():
    """`acceptable_license_types` is optional on the wire; empty list is
    the default (no constraint — any license class accepted)."""
    payload = referral_payload()
    payload.pop("acceptable_license_types", None)
    p = post_create_adapter.validate_python(payload)
    assert p.acceptable_license_types == []


def test_post_create_referral_accepts_acceptable_license_types_list():
    """The "psychiatrist OR PMHNP" disjunction the corpus surfaces lands
    as a two-element list — the wire model accepts multi-select directly."""
    p = post_create_adapter.validate_python(
        referral_payload(acceptable_license_types=["md", "pmhnp"])
    )
    assert p.acceptable_license_types == ["md", "pmhnp"]


def test_post_create_referral_coerces_scalar_license_type_to_list():
    """HTML form checkbox single-value submits land as a bare string;
    `scalar_to_list` normalizes to a one-element list before the
    `Literal[*LICENSE_TYPES]` per-member check."""
    p = post_create_adapter.validate_python(
        referral_payload(acceptable_license_types="lcsw")
    )
    assert p.acceptable_license_types == ["lcsw"]


def test_post_create_referral_rejects_unknown_license_type():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            referral_payload(acceptable_license_types=["not_a_real_license"])
        )


def test_post_create_referral_defaults_clinical_niches_to_empty_list():
    """`clinical_niches` is optional on the wire; empty list is the
    default (no niche-specific constraint)."""
    payload = referral_payload()
    payload.pop("clinical_niches", None)
    p = post_create_adapter.validate_python(payload)
    assert p.clinical_niches == []


def test_post_create_referral_accepts_clinical_niches_list():
    p = post_create_adapter.validate_python(
        referral_payload(clinical_niches=["DGBI", "ADHD in women"])
    )
    assert p.clinical_niches == ["DGBI", "ADHD in women"]


def test_post_create_referral_coerces_scalar_clinical_niche_to_list():
    """Single-value tag submits as a bare string; `clean_free_form_tags`
    wraps it in a one-element list before per-member `str` validation."""
    p = post_create_adapter.validate_python(referral_payload(clinical_niches="DGBI"))
    assert p.clinical_niches == ["DGBI"]


def test_post_create_referral_strips_and_drops_empty_clinical_niches():
    """Free-form tags: stripped on the wire, empty/whitespace-only
    entries dropped silently."""
    p = post_create_adapter.validate_python(
        referral_payload(clinical_niches=["  DGBI  ", "", "   ", "catatonia"])
    )
    assert p.clinical_niches == ["DGBI", "catatonia"]


def test_post_create_referral_dedupes_clinical_niches():
    """Duplicate-tag submissions collapse to first-occurrence order."""
    p = post_create_adapter.validate_python(
        referral_payload(clinical_niches=["DGBI", "catatonia", "DGBI"])
    )
    assert p.clinical_niches == ["DGBI", "catatonia"]


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


def test_post_create_referral_rejects_unknown_insurance_carrier():
    """Vocabulary check on the JSON list: an unknown carrier token
    (#1358 PR-e — `insurance_carriers` is now `list[Literal[*INSURANCE_CARRIERS]]`)."""
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(
            referral_payload(insurance_carriers=["my_local_co_op"])
        )


def test_post_create_referral_allows_empty_carrier_list():
    """Empty `insurance_carriers` list is valid with any combination of
    the three payment-path booleans — e.g. an in-network-friendly
    referral whose carrier is undecided, or a private-pay-only one."""
    for bools in (
        {"accepts_in_network": True},
        {"accepts_private_pay": True},
        {"accepts_in_network": True, "accepts_private_pay": True},
        {},  # All false — shape-valid even if uncommon.
    ):
        p = post_create_adapter.validate_python(
            referral_payload(insurance_carriers=[], **bools)
        )
        assert p.insurance_carriers == []


def test_post_create_referral_accepts_multiple_carriers():
    """Multi-select: a referral can list multiple acceptable carriers.
    Mirrors `ClinicianAffiliation.in_network_carriers` (#1358 PR-e)."""
    p = post_create_adapter.validate_python(
        referral_payload(
            accepts_in_network=True,
            insurance_carriers=["cigna", "aetna"],
        )
    )
    assert p.accepts_in_network is True
    assert p.insurance_carriers == ["cigna", "aetna"]


def test_post_create_referral_payment_paths_independent():
    """The three payment-path booleans are independent — any subset
    (including all-true or all-false) round-trips through the schema."""
    p = post_create_adapter.validate_python(
        referral_payload(
            accepts_in_network=True,
            accepts_out_of_network_superbill=True,
            accepts_private_pay=True,
            insurance_carriers=["anthem_bcbs"],
        )
    )
    assert p.accepts_in_network is True
    assert p.accepts_out_of_network_superbill is True
    assert p.accepts_private_pay is True
    assert p.insurance_carriers == ["anthem_bcbs"]


def test_post_create_referral_payment_paths_default_false():
    """When a payment-path bool is omitted entirely it defaults to
    False — the schema does not require any to be true."""
    payload = referral_payload()
    for key in (
        "accepts_in_network",
        "accepts_out_of_network_superbill",
        "accepts_private_pay",
    ):
        payload.pop(key, None)
    payload.pop("insurance_carriers", None)
    p = post_create_adapter.validate_python(payload)
    assert p.accepts_in_network is False
    assert p.accepts_out_of_network_superbill is False
    assert p.accepts_private_pay is False
    assert p.insurance_carriers == []


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
    assert snap["accepts_in_network"] == detail_attrs["accepts_in_network"]
    assert (
        snap["accepts_out_of_network_superbill"]
        == detail_attrs["accepts_out_of_network_superbill"]
    )
    assert snap["accepts_private_pay"] == detail_attrs["accepts_private_pay"]
    assert snap["insurance_carriers"] == detail_attrs["insurance_carriers"]


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
    assert isinstance(p, ClinicianOpeningCreate)
    assert p.kind == "clinician_opening"
    # Insurance posture moved to Clinician in #449; PA no longer carries
    # `sliding_scale` / `payment_situation` / `cost` on the wire.


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
        {"kind": "clinician_opening", "schedule_text": "New cohort starts Jun 1"}
    )
    assert p.schedule_text == "New cohort starts Jun 1"


@pytest.mark.parametrize(
    "token",
    ["group_therapy", "family_therapy", "couples_therapy"],
)
def test_post_create_referral_accepts_new_services_tokens(token):
    """CR shares the `REFERRAL_SERVICES` vocab with PA; widening
    propagates to both (#440)."""
    p = post_create_adapter.validate_python(referral_payload(services=[token]))
    assert p.services == [token]


@pytest.mark.parametrize("token", INSURANCE_CARRIERS)
def test_post_create_referral_accepts_all_insurance_carriers(token):
    """Every `INSURANCE_CARRIERS` token validates as an element of
    `insurance_carriers` (shared vocab with Clinician, now both
    sides are lists — #1358 PR-e)."""
    p = post_create_adapter.validate_python(
        referral_payload(insurance_carriers=[token])
    )
    assert p.insurance_carriers == [token]


def test_post_create_referral_rejects_retired_in_network_token():
    """The old `insurance` enum is gone. A payload sending the legacy
    field gets ignored as an unknown field (extra='forbid' on
    WirePayload), so this 422s."""
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(referral_payload(insurance="in_network"))


def test_post_create_opening_requires_clinician_affiliation_id():
    """The picker submits `clinician_affiliation_id`; `clinician_id` is
    server-derived from it. The affiliation FK is the only required
    wire field on the thin opening shape (#1358 PR-f sub-3)."""
    payload = opening_payload()
    payload.pop("clinician_affiliation_id")
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


def test_post_create_opening_accepts_description():
    """`description` is the announcement-core free-text field on the
    thin opening shape; `referral_instructions` / `website` moved to
    the affiliation in #1358 PR-f sub-3."""
    p = post_create_adapter.validate_python(
        opening_payload(description="Lead narrative pitch.")
    )
    assert p.description == "Lead narrative pitch."


def test_post_create_opening_description_defaults_none():
    """`description` is optional; absent → None."""
    payload = opening_payload()
    payload.pop("description", None)
    p = post_create_adapter.validate_python(payload)
    assert p.description is None


def test_post_create_opening_strips_description_whitespace():
    p = post_create_adapter.validate_python(opening_payload(description="  trim me  "))
    assert p.description == "trim me"


def test_post_update_opening_accepts_description_only():
    """A PATCH that only sets `description` is a valid partial update."""
    p = post_update_adapter.validate_python(
        {"kind": "clinician_opening", "description": "Updated pitch."}
    )
    assert p.description == "Updated pitch."


def test_post_update_opening_accepts_clinician_id_only():
    """A PATCH that only repoints `clinician_id` is a valid partial update."""
    new_clinician_id = uuid.uuid4()
    p = post_update_adapter.validate_python(
        {"kind": "clinician_opening", "clinician_id": str(new_clinician_id)}
    )
    assert isinstance(p, ClinicianOpeningUpdate)
    assert p.clinician_id == new_clinician_id


def test_post_update_opening_strips_whitespace():
    """`description` is a free-text PA field — whitespace stripping still
    applies. (Practice-name stripping moved to Clinician with #448.)"""
    p = post_update_adapter.validate_python(
        {"kind": "clinician_opening", "description": "  Renamed  "}
    )
    assert p.description == "Renamed"


def test_post_update_opening_requires_at_least_one_field():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python({"kind": "clinician_opening"})


def test_post_update_opening_rejects_whitespace_only():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "clinician_opening", "description": "   "}
        )


def test_post_update_opening_rejects_unknown_field():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {
                "kind": "clinician_opening",
                "description": "Acme",
                "evil": True,
            }
        )


def test_audit_snapshot_for_opening_post():
    """Snapshotting a `kind='clinician_opening'` post flattens through
    `opening_detail`."""
    owner_id = uuid.uuid4()
    detail_attrs = opening_payload()
    detail_attrs.pop("kind")
    post = SimpleNamespace(
        kind="clinician_opening",
        owner_id=owner_id,
        referral_detail=None,
        opening_detail=SimpleNamespace(**detail_attrs),
    )
    snap = post_audit_snapshot(post)
    assert snap["kind"] == "clinician_opening"
    assert snap["owner_id"] == str(owner_id)
    # The audit row records the FK to the Clinician, not the
    # dereferenced practice fields. Practice-name/location/sessions live
    # on Clinician's ClinicianAffiliation — snapshotted via that entity's audit path.
    assert snap["clinician_id"] == detail_attrs["clinician_id"]
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
        (ReferralRead, "gender", GENDERS),
        # Create variants
        (ReferralCreate, "gender", GENDERS),
        # Update variants (Optional[Literal[*TUPLE]])
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
        (opening_payload, "clinician_opening"),
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


@pytest.mark.parametrize("kind", ["referral", "clinician_opening"])
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
    ["referral", "clinician_opening"],
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
    ["referral", "clinician_opening"],
)
def test_post_update_desired_times_rejects_unknown_token(kind):
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": kind, "desired_times": ["monday_brunch"]}
        )


# --- services multi-select ----------------------------------------------
#
# After #1358 PR-f sub-3, `services` is a referral-only wire field — on
# the offering side it moved to ``ClinicianAffiliation`` / ``Program``.


def test_post_create_referral_services_defaults_to_empty_list():
    """CR's `services` is optional with `[]` default — omitting it is fine."""
    payload = referral_payload()
    payload.pop("services", None)
    p = post_create_adapter.validate_python(payload)
    assert p.services == []


def test_post_create_referral_services_accepts_subset():
    p = post_create_adapter.validate_python(
        referral_payload(services=["evaluation", "psychotherapy"])
    )
    assert p.services == ["evaluation", "psychotherapy"]


def test_post_create_referral_services_coerces_scalar_to_singleton_list():
    """Same json-enc 1-checkbox-collapses-to-scalar story as `desired_times`
    — the shared `_scalar_to_list` BeforeValidator handles it."""
    p = post_create_adapter.validate_python(referral_payload(services="evaluation"))
    assert p.services == ["evaluation"]


def test_post_create_referral_services_rejects_unknown_token():
    with pytest.raises(ValidationError):
        post_create_adapter.validate_python(referral_payload(services=["telekinesis"]))


def test_post_update_referral_services_coerces_scalar_to_singleton_list():
    p = post_update_adapter.validate_python(
        {"kind": "referral", "services": "evaluation"}
    )
    assert p.services == ["evaluation"]


def test_post_update_referral_services_accepts_empty_list():
    """CR's `services` is optional, so PATCHing `services: []` clears the
    selection — same semantics as `desired_times`."""
    p = post_update_adapter.validate_python({"kind": "referral", "services": []})
    assert p.services == []


def test_post_update_referral_services_rejects_unknown_token():
    with pytest.raises(ValidationError):
        post_update_adapter.validate_python(
            {"kind": "referral", "services": ["telekinesis"]}
        )


# Label/icon coverage for every vocabulary — including the multi-attribute
# `ClientAgeGroup` / `DesiredTime*` — is pinned centrally in
# `src/domain/models/test_enums.py`, since each `*_LABELS` / `*_ICONS` dict now
# derives from its `LabeledChoice` class and so can't drift from the value set.
