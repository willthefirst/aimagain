"""Tests for the clinician wire schemas.

Covers:
- `ClinicianCreate` minimum surface (first / last / NPI). Affiliation,
  location, availability, and insurance fields are no longer on create
  — they're added via the affiliation sub-resource after the row exists.
- `ClinicianUpdate` partial-update rule + carrier patch shapes.
- NPI validator shapes (required on Create, optional on Update).
- `ClinicianRead` round-trips a nested dict (with or without an
  affiliation-derived block) through `model_validate`, including
  sub-entity lists.
- `test_schema_literals_match_model_tuples` guards that `Literal[*TUPLE]`
  types stay aligned with the source-of-truth tuples in
  `src/domain/models/enums.py` for the Update + sub-entity schemas.
"""

import uuid
from datetime import date, datetime, timezone
from typing import get_args

import pytest
from pydantic import ValidationError

from src.domain.logic.clinicians.schema import (
    ClinicianCertificationCreate,
    ClinicianCertificationUpdate,
    ClinicianCreate,
    ClinicianEducationCreate,
    ClinicianEducationUpdate,
    ClinicianLicensureCreate,
    ClinicianLicensureUpdate,
    ClinicianRead,
    ClinicianUpdate,
)
from src.domain.models.enums import (
    CERTIFICATION_TYPES,
    EDUCATION_TYPES,
    INSURANCE_CARRIER_LABELS,
    INSURANCE_CARRIERS,
    LICENSE_TYPES,
    US_STATES,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


_VALID_CREATE = {"first_name": "Jane", "last_name": "Smith", "npi": "1234567890"}


# --- ClinicianCreate ----------------------------------------------------


def test_clinician_create_accepts_minimal_payload():
    p = ClinicianCreate(**_VALID_CREATE)
    assert p.first_name == "Jane"
    assert p.last_name == "Smith"
    assert p.npi == "1234567890"


def test_clinician_create_requires_npi():
    with pytest.raises(ValidationError):
        ClinicianCreate(first_name="Jane", last_name="Smith")


@pytest.mark.parametrize("blank", ["", "   "])
def test_clinician_create_rejects_blank_npi(blank):
    with pytest.raises(ValidationError):
        ClinicianCreate(first_name="Jane", last_name="Smith", npi=blank)


@pytest.mark.parametrize(
    "bad", ["123", "123456789", "12345678901", "12345abcde", "  123456 7890"]
)
def test_clinician_create_rejects_malformed_npi(bad):
    with pytest.raises(ValidationError):
        ClinicianCreate(first_name="Jane", last_name="Smith", npi=bad)


def test_clinician_create_rejects_unknown_field():
    """`WirePayload`'s extra-forbid covers anything not declared on the
    minimal Create schema — including fields that used to live there
    (org_id, location_*, in_person_sessions, etc.)."""
    for stray in (
        "org_id",
        "solo_practice",
        "practice_name",
        "location_city",
        "in_person_sessions",
        "in_network_carriers",
        "cost",
        "licensures",
    ):
        with pytest.raises(ValidationError, match="extra"):
            ClinicianCreate(**_VALID_CREATE, **{stray: "boom"})


# --- ClinicianUpdate ----------------------------------------------------


@pytest.mark.parametrize(
    "model_cls",
    [
        ClinicianUpdate,
        ClinicianLicensureUpdate,
        ClinicianEducationUpdate,
        ClinicianCertificationUpdate,
    ],
)
def test_update_requires_at_least_one_field(model_cls):
    with pytest.raises(ValidationError):
        model_cls()


def test_clinician_update_accepts_first_name_only():
    """Person-level partial patch — the canonical "rename the clinician"
    PATCH that the edit form sends after #1308 dropped per-affiliation
    fields from this schema."""
    upd = ClinicianUpdate(first_name="Janet")
    assert upd.first_name == "Janet"
    assert upd.last_name is None
    assert upd.npi is None


def test_clinician_update_accepts_npi_patch():
    p = ClinicianUpdate(npi="1234567890")
    assert p.npi == "1234567890"


def test_clinician_update_rejects_malformed_npi():
    with pytest.raises(ValidationError):
        ClinicianUpdate(npi="abc")


def test_clinician_update_rejects_per_affiliation_fields():
    """Per-affiliation posture (location, availability, insurance,
    cost, org_id) is edited on `ClinicianAffiliation`, not on the
    person — extra="forbid" rejects them here so a stale client
    fails loudly instead of having its writes silently dropped."""
    for stray_kwarg in (
        {"org_id": uuid.uuid4()},
        {"location_city": "Brooklyn"},
        {"in_person_sessions": "yes"},
        {"virtual_sessions": "no"},
        {"in_network_carriers": ["aetna"]},
        {"accepts_out_of_network": True},
        {"sliding_scale": True},
        {"cost": "$150"},
    ):
        with pytest.raises(ValidationError):
            ClinicianUpdate(first_name="Janet", **stray_kwarg)


# --- ClinicianRead ------------------------------------------------------


def test_clinician_read_round_trips_npi():
    """`ClinicianRead.model_validate` carries `npi` through unchanged."""
    now = _now()
    p = ClinicianRead.model_validate(
        {
            "id": uuid.uuid4(),
            "owner_id": uuid.uuid4(),
            "created_at": now,
            "updated_at": now,
            "org_id": uuid.uuid4(),
            "org_name": "Sunrise",
            "npi": "1234567890",
            "first_name": "Jane",
            "last_name": "Smith",
            "location_city": "Boise",
            "location_state": "ID",
            "location_zip": "83702",
            "in_person_sessions": "yes",
            "virtual_sessions": "no",
            "accepts_out_of_network": True,
            "in_network_carriers": [],
            "sliding_scale": False,
            "cost": None,
        }
    )
    assert p.npi == "1234567890"


def test_clinician_read_tolerates_missing_affiliation_fields():
    """A clinician with no `ClinicianAffiliation` reads through with all
    affiliation-derived fields as `None` (or `[]` for carriers)."""
    now = _now()
    p = ClinicianRead.model_validate(
        {
            "id": uuid.uuid4(),
            "owner_id": uuid.uuid4(),
            "created_at": now,
            "updated_at": now,
            "first_name": "Jane",
            "last_name": "Smith",
            "npi": "1234567890",
        }
    )
    assert p.org_id is None
    assert p.org_name is None
    assert p.in_person_sessions is None
    assert p.in_network_carriers == []
    assert p.sliding_scale is None


def test_clinician_read_validates_from_nested_dict():
    """`ClinicianRead.model_validate` constructs nested sub-entity Read
    schemas without needing real ORM objects."""
    now = _now()
    payload = {
        "id": uuid.uuid4(),
        "owner_id": uuid.uuid4(),
        "created_at": now,
        "updated_at": now,
        "org_id": uuid.uuid4(),
        "org_name": "Sunrise",
        "first_name": "Jane",
        "last_name": "Smith",
        "location_city": "Boise",
        "location_state": "ID",
        "location_zip": "83702",
        "in_person_sessions": "yes",
        "virtual_sessions": "no",
        "accepts_out_of_network": False,
        "in_network_carriers": [],
        "sliding_scale": False,
        "cost": None,
        "licensures": [
            {
                "id": uuid.uuid4(),
                "clinician_id": uuid.uuid4(),
                "created_at": now,
                "updated_at": now,
                "license_type": "lcsw",
                "license_number": "L12345",
                "issuing_state": "ID",
                "expiration_date": date(2030, 1, 1),
            }
        ],
        "educations": [
            {
                "id": uuid.uuid4(),
                "clinician_id": uuid.uuid4(),
                "created_at": now,
                "updated_at": now,
                "education_type": "msw",
                "institution": "State U",
                "month_completed": "2010-05",
            }
        ],
        "certifications": [
            {
                "id": uuid.uuid4(),
                "clinician_id": uuid.uuid4(),
                "created_at": now,
                "updated_at": now,
                "certification_type": "emdr",
                "certifying_body": "EMDRIA",
                "expiration_date": None,
            }
        ],
    }
    clinician = ClinicianRead.model_validate(payload)
    assert clinician.org_name == "Sunrise"
    assert len(clinician.licensures) == 1


# --- Sub-entity Create vocabulary ---------------------------------------


def test_licensure_create_rejects_unknown_license_type():
    with pytest.raises(ValidationError):
        ClinicianLicensureCreate(
            license_type="not_a_real_type",
            license_number="L12345",
            issuing_state="CA",
        )


def test_licensure_create_rejects_invalid_state():
    with pytest.raises(ValidationError):
        ClinicianLicensureCreate(
            license_type="lcsw",
            license_number="L12345",
            issuing_state="ZZ",
        )


def test_education_create_rejects_unknown_education_type():
    with pytest.raises(ValidationError):
        ClinicianEducationCreate(
            education_type="not_a_real_degree",
            institution="State U",
        )


def test_certification_create_rejects_unknown_certification_type():
    with pytest.raises(ValidationError):
        ClinicianCertificationCreate(
            certification_type="not_a_real_cert",
            certifying_body="Some Body",
        )


def test_licensure_create_rejects_unknown_field():
    with pytest.raises(ValidationError):
        ClinicianLicensureCreate(
            license_type="lcsw",
            license_number="L12345",
            issuing_state="CA",
            stray_field="boom",
        )


# --- Affirming-identity (person-level) ----------------------------------


def test_clinician_update_accepts_affirming_identities_patch():
    """`affirming_identities` is a JSON multi-checkbox field on the
    person-level Update — clinicians self-claim who they affirm. Empty
    list and a populated list both validate; `None` (omitted) means
    "leave unchanged" per `PartialUpdate` semantics."""
    upd = ClinicianUpdate(affirming_identities=["lgbtq", "trans"])
    assert upd.affirming_identities == ["lgbtq", "trans"]


def test_clinician_update_accepts_empty_affirming_identities():
    """Explicit empty list = clear the claim list. Distinct from `None`
    (omitted = leave unchanged)."""
    upd = ClinicianUpdate(affirming_identities=[])
    assert upd.affirming_identities == []


def test_clinician_update_coerces_scalar_affirming_identity_to_list():
    """HTML form checkboxes with a single checked value submit as a
    scalar string — `scalar_to_list` normalizes to `["value"]` before
    `Literal[*AFFIRMING_IDENTITIES]` validation."""
    upd = ClinicianUpdate(affirming_identities="lgbtq")
    assert upd.affirming_identities == ["lgbtq"]


def test_clinician_update_rejects_unknown_affirming_identity():
    with pytest.raises(ValidationError):
        ClinicianUpdate(affirming_identities=["not_a_real_token"])


def test_clinician_create_rejects_affirming_identities_on_create():
    """Create stays minimal: the field is claim-management, set later
    via PATCH. Stays out of the minimal-Create surface so the create
    payload isn't widened ahead of need."""
    with pytest.raises(ValidationError, match="extra"):
        ClinicianCreate(**_VALID_CREATE, affirming_identities=["lgbtq"])


def test_clinician_read_defaults_affirming_identities_to_empty_list():
    """A row with no claims reads as `[]`, matching the column's
    server-side default."""
    now = _now()
    p = ClinicianRead.model_validate(
        {
            "id": uuid.uuid4(),
            "owner_id": uuid.uuid4(),
            "created_at": now,
            "updated_at": now,
            "first_name": "Jane",
            "last_name": "Smith",
            "npi": "1234567890",
        }
    )
    assert p.affirming_identities == []


def test_clinician_read_round_trips_affirming_identities():
    now = _now()
    p = ClinicianRead.model_validate(
        {
            "id": uuid.uuid4(),
            "owner_id": uuid.uuid4(),
            "created_at": now,
            "updated_at": now,
            "first_name": "Jane",
            "last_name": "Smith",
            "npi": "1234567890",
            "affirming_identities": ["lgbtq", "neurodiversity"],
        }
    )
    assert p.affirming_identities == ["lgbtq", "neurodiversity"]


# --- Clinical-niche (free-form tags) ------------------------------------


def test_clinician_update_accepts_clinical_niches_patch():
    """`clinical_niches` is a free-form `list[str]` on the person-level
    Update — clinicians self-claim niches like "DGBI" or "ADHD in
    women". Empty list and populated list both validate; `None` (omitted)
    means "leave unchanged" per `PartialUpdate` semantics."""
    upd = ClinicianUpdate(clinical_niches=["DGBI", "complex trauma"])
    assert upd.clinical_niches == ["DGBI", "complex trauma"]


def test_clinician_update_accepts_empty_clinical_niches():
    """Explicit empty list = clear the niche list. Distinct from `None`
    (omitted = leave unchanged)."""
    upd = ClinicianUpdate(clinical_niches=[])
    assert upd.clinical_niches == []


def test_clinician_update_coerces_scalar_clinical_niche_to_list():
    """Single-value tag input lands as a scalar string — the shared
    `clean_free_form_tags` validator wraps it in a one-element list
    before per-member `str` validation."""
    upd = ClinicianUpdate(clinical_niches="DGBI")
    assert upd.clinical_niches == ["DGBI"]


def test_clinician_update_strips_and_drops_empty_clinical_niches():
    """Free-form tags are stripped; empty/whitespace-only entries are
    dropped silently rather than 422'ing the whole submission."""
    upd = ClinicianUpdate(clinical_niches=["  DGBI ", "", "   ", "catatonia"])
    assert upd.clinical_niches == ["DGBI", "catatonia"]


def test_clinician_update_dedupes_clinical_niches():
    """A UI that accidentally submits the same tag twice should collapse
    to one entry — preserve first-occurrence order."""
    upd = ClinicianUpdate(clinical_niches=["DGBI", "catatonia", "DGBI"])
    assert upd.clinical_niches == ["DGBI", "catatonia"]


def test_clinician_create_rejects_clinical_niches_on_create():
    """Create stays minimal: niches are claim-management, set later via
    PATCH (mirrors `affirming_identities`)."""
    with pytest.raises(ValidationError, match="extra"):
        ClinicianCreate(**_VALID_CREATE, clinical_niches=["DGBI"])


def test_clinician_read_defaults_clinical_niches_to_empty_list():
    """A row with no niches reads as `[]`, matching the column's
    server-side default."""
    now = _now()
    p = ClinicianRead.model_validate(
        {
            "id": uuid.uuid4(),
            "owner_id": uuid.uuid4(),
            "created_at": now,
            "updated_at": now,
            "first_name": "Jane",
            "last_name": "Smith",
            "npi": "1234567890",
        }
    )
    assert p.clinical_niches == []


def test_clinician_read_round_trips_clinical_niches():
    now = _now()
    p = ClinicianRead.model_validate(
        {
            "id": uuid.uuid4(),
            "owner_id": uuid.uuid4(),
            "created_at": now,
            "updated_at": now,
            "first_name": "Jane",
            "last_name": "Smith",
            "npi": "1234567890",
            "clinical_niches": ["DGBI", "ADHD in women"],
        }
    )
    assert p.clinical_niches == ["DGBI", "ADHD in women"]


# --- Insurance carrier label guardrail ----------------------------------


def test_insurance_carriers_labels_cover_all_tokens():
    """Every `INSURANCE_CARRIERS` token must have an entry in
    `INSURANCE_CARRIER_LABELS` so the form-render macro can resolve a
    label at request time."""
    assert set(INSURANCE_CARRIER_LABELS) == set(INSURANCE_CARRIERS)


# --- Literal-tuple lockstep ---------------------------------------------


def _literal_args(model_cls, field_name: str) -> tuple[str, ...]:
    """Pull the `Literal[...]` accepted values off a Pydantic field's
    annotation, regardless of `Optional` wrapping."""
    annotation = model_cls.model_fields[field_name].annotation
    args = get_args(annotation)
    if args:
        for arm in args:
            literal_values = get_args(arm)
            if literal_values and all(isinstance(v, str) for v in literal_values):
                return literal_values
        if all(isinstance(a, str) for a in args):
            return args
    return ()


@pytest.mark.parametrize(
    "model_cls,field,expected",
    [
        (ClinicianLicensureCreate, "license_type", LICENSE_TYPES),
        (ClinicianLicensureCreate, "issuing_state", US_STATES),
        (ClinicianEducationCreate, "education_type", EDUCATION_TYPES),
        (ClinicianCertificationCreate, "certification_type", CERTIFICATION_TYPES),
        (ClinicianLicensureUpdate, "license_type", LICENSE_TYPES),
        (ClinicianLicensureUpdate, "issuing_state", US_STATES),
        (ClinicianEducationUpdate, "education_type", EDUCATION_TYPES),
        (ClinicianCertificationUpdate, "certification_type", CERTIFICATION_TYPES),
    ],
)
def test_schema_literals_match_model_tuples(model_cls, field, expected):
    """Schema `Literal[*TUPLE]`s and DB CHECK universes must agree,
    sourced from the tuples in `src/domain/models/enums.py`. If you add
    or rename a vocabulary value, update both places (and the migration);
    this guardrail keeps them honest."""
    assert set(_literal_args(model_cls, field)) == set(expected)
