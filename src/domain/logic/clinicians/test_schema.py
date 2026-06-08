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
    LOCATION_AVAILABILITY_OPTIONS,
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


def test_clinician_update_accepts_single_field():
    new_org = uuid.uuid4()
    upd = ClinicianUpdate(org_id=new_org)
    assert upd.org_id == new_org
    assert upd.location is None


def test_clinician_update_accepts_npi_patch():
    p = ClinicianUpdate(npi="1234567890")
    assert p.npi == "1234567890"


def test_clinician_update_rejects_malformed_npi():
    with pytest.raises(ValidationError):
        ClinicianUpdate(npi="abc")


def test_clinician_update_accepts_carrier_list_patch():
    p = ClinicianUpdate(in_network_carriers=["aetna"])
    assert p.in_network_carriers == ["aetna"]


def test_clinician_update_accepts_empty_carrier_list_patch():
    p = ClinicianUpdate(in_network_carriers=[])
    assert p.in_network_carriers == []


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
        (ClinicianUpdate, "in_person_sessions", LOCATION_AVAILABILITY_OPTIONS),
    ],
)
def test_schema_literals_match_model_tuples(model_cls, field, expected):
    """Schema `Literal[*TUPLE]`s and DB CHECK universes must agree,
    sourced from the tuples in `src/domain/models/enums.py`. If you add
    or rename a vocabulary value, update both places (and the migration);
    this guardrail keeps them honest."""
    assert set(_literal_args(model_cls, field)) == set(expected)
