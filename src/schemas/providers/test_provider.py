"""Tests for the provider wire schemas.

Covers:
- Controlled-vocabulary fields reject values outside their tuples.
- Create variants reject unknown fields (`extra="forbid"`).
- Update variants raise `ValidationError` when no editable field is
  set (the at-least-one-field rule).
- `ProviderRead` round-trips a nested dict through
  `model_validate`, including sub-entity lists.
- `test_schema_literals_match_model_tuples` guards that `Literal[*TUPLE]`
  types stay aligned with the source-of-truth tuples in
  `src/models/enums.py`.
"""

import uuid
from datetime import date, datetime, timezone
from typing import get_args

import pytest
from pydantic import ValidationError

from src.models.enums import (
    CERTIFICATION_TYPES,
    EDUCATION_TYPES,
    LICENSE_TYPES,
    LOCATION_AVAILABILITY_OPTIONS,
    US_STATES,
)
from src.schemas.providers.provider import (
    ProviderCertificationCreate,
    ProviderCertificationUpdate,
    ProviderCreate,
    ProviderEducationCreate,
    ProviderEducationUpdate,
    ProviderLicensureCreate,
    ProviderLicensureUpdate,
    ProviderRead,
    ProviderUpdate,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _provider_create_kwargs(**overrides):
    """Minimum-valid kwargs for `ProviderCreate`."""
    base = {
        "practice_name": "Sunrise Counseling",
        "location_city": "Boise",
        "location_state": "ID",
        "location_zip": "83702",
        "in_person_sessions": "yes",
        "virtual_sessions": "no",
    }
    base.update(overrides)
    return base


# --- Controlled-vocabulary rejection ------------------------------------


def test_licensure_create_rejects_unknown_license_type():
    with pytest.raises(ValidationError):
        ProviderLicensureCreate(
            license_type="not_a_real_type",
            license_number="L12345",
            issuing_state="CA",
        )


def test_licensure_create_rejects_invalid_state():
    with pytest.raises(ValidationError):
        ProviderLicensureCreate(
            license_type="lcsw",
            license_number="L12345",
            issuing_state="ZZ",
        )


def test_education_create_rejects_unknown_education_type():
    with pytest.raises(ValidationError):
        ProviderEducationCreate(
            education_type="not_a_real_degree",
            institution="State U",
        )


def test_certification_create_rejects_unknown_certification_type():
    with pytest.raises(ValidationError):
        ProviderCertificationCreate(
            certification_type="not_a_real_cert",
            certifying_body="Some Body",
        )


def test_provider_create_rejects_invalid_in_person_sessions():
    with pytest.raises(ValidationError):
        ProviderCreate(
            **_provider_create_kwargs(in_person_sessions="maybe"),
        )


# --- extra="forbid" -----------------------------------------------------


def test_provider_create_rejects_unknown_field():
    with pytest.raises(ValidationError):
        ProviderCreate(
            **_provider_create_kwargs(),
            stray_field="boom",
        )


def test_licensure_create_rejects_unknown_field():
    with pytest.raises(ValidationError):
        ProviderLicensureCreate(
            license_type="lcsw",
            license_number="L12345",
            issuing_state="CA",
            stray_field="boom",
        )


# --- At-least-one-field on Update ---------------------------------------


@pytest.mark.parametrize(
    "model_cls",
    [
        ProviderUpdate,
        ProviderLicensureUpdate,
        ProviderEducationUpdate,
        ProviderCertificationUpdate,
    ],
)
def test_update_requires_at_least_one_field(model_cls):
    with pytest.raises(ValidationError):
        model_cls()


def test_provider_update_accepts_single_field():
    """Sanity check: setting one field is enough — the rule fires only
    when *every* field is `None`."""
    upd = ProviderUpdate(practice_name="New Name")
    assert upd.practice_name == "New Name"
    assert upd.location_city is None


# --- Create payload smoke tests -----------------------------------------


def test_provider_create_strips_practice_name():
    p = ProviderCreate(**_provider_create_kwargs(practice_name="  Sunrise  "))
    assert p.practice_name == "Sunrise"


def test_provider_create_rejects_non_5_digit_zip():
    """Smoke test that the imported `ZipText` alias is wired up."""
    with pytest.raises(ValidationError):
        ProviderCreate(**_provider_create_kwargs(location_zip="123"))


def test_provider_create_accepts_nested_credential_lists():
    p = ProviderCreate(
        **_provider_create_kwargs(),
        licensures=[
            {
                "license_type": "lcsw",
                "license_number": "L12345",
                "issuing_state": "ID",
            }
        ],
        educations=[
            {"education_type": "msw", "institution": "State U"},
        ],
        certifications=[
            {"certification_type": "emdr", "certifying_body": "EMDRIA"},
        ],
    )
    assert len(p.licensures) == 1
    assert p.licensures[0].license_type == "lcsw"
    assert p.educations[0].institution == "State U"
    assert p.certifications[0].certification_type == "emdr"


def test_provider_create_defaults_credential_lists_to_empty():
    p = ProviderCreate(**_provider_create_kwargs())
    assert p.licensures == []
    assert p.educations == []
    assert p.certifications == []


# --- Read from nested dict ----------------------------------------------


def test_provider_read_validates_from_nested_dict():
    """`ProviderRead.model_validate` should construct the nested
    sub-entity Read schemas without needing real ORM objects."""
    provider_id = uuid.uuid4()
    now = _now()
    payload = {
        "id": provider_id,
        "user_id": uuid.uuid4(),
        "created_at": now,
        "updated_at": now,
        "practice_name": "Sunrise",
        "location_city": "Boise",
        "location_state": "ID",
        "location_zip": "83702",
        "in_person_sessions": "yes",
        "virtual_sessions": "no",
        "licensures": [
            {
                "id": uuid.uuid4(),
                "provider_id": provider_id,
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
                "provider_id": provider_id,
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
                "provider_id": provider_id,
                "created_at": now,
                "updated_at": now,
                "certification_type": "emdr",
                "certifying_body": "EMDRIA",
                "expiration_date": None,
            }
        ],
    }

    provider = ProviderRead.model_validate(payload)

    assert provider.practice_name == "Sunrise"
    assert len(provider.licensures) == 1
    assert provider.licensures[0].license_type == "lcsw"
    assert provider.educations[0].month_completed == "2010-05"
    assert provider.certifications[0].expiration_date is None


# --- Schema-literal vs model-tuple guardrail ----------------------------


def _literal_args(model_cls, field_name: str) -> tuple[str, ...]:
    """Pull the `Literal[...]` accepted values off a Pydantic field's
    annotation, regardless of `Optional` wrapping. Mirrors the helper
    in `test_post.py`."""
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
        # Create variants
        (ProviderLicensureCreate, "license_type", LICENSE_TYPES),
        (ProviderLicensureCreate, "issuing_state", US_STATES),
        (ProviderEducationCreate, "education_type", EDUCATION_TYPES),
        (ProviderCertificationCreate, "certification_type", CERTIFICATION_TYPES),
        (ProviderCreate, "location_state", US_STATES),
        (ProviderCreate, "in_person_sessions", LOCATION_AVAILABILITY_OPTIONS),
        (ProviderCreate, "virtual_sessions", LOCATION_AVAILABILITY_OPTIONS),
        # Update variants (Optional[Literal[*TUPLE]])
        (ProviderLicensureUpdate, "license_type", LICENSE_TYPES),
        (ProviderLicensureUpdate, "issuing_state", US_STATES),
        (ProviderEducationUpdate, "education_type", EDUCATION_TYPES),
        (ProviderCertificationUpdate, "certification_type", CERTIFICATION_TYPES),
        (ProviderUpdate, "location_state", US_STATES),
        (ProviderUpdate, "in_person_sessions", LOCATION_AVAILABILITY_OPTIONS),
    ],
)
def test_schema_literals_match_model_tuples(model_cls, field, expected):
    """Schema `Literal[*TUPLE]`s and DB CHECK universes must agree,
    sourced from the tuples in `src/models/enums.py`. If you add or
    rename a vocabulary value, update both places (and the migration);
    this guardrail keeps them honest."""
    assert set(_literal_args(model_cls, field)) == set(expected)
