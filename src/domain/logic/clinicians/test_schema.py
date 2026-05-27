"""Tests for the clinician wire schemas.

Covers:
- Controlled-vocabulary fields reject values outside their tuples.
- Create variants reject unknown fields (`extra="forbid"`).
- Update variants raise `ValidationError` when no editable field is
  set (the at-least-one-field rule).
- `ProviderRead` round-trips a nested dict through
  `model_validate`, including sub-entity lists.
- `test_schema_literals_match_model_tuples` guards that `Literal[*TUPLE]`
  types stay aligned with the source-of-truth tuples in
  `src/domain/models/enums.py`.
"""

import uuid
from datetime import date, datetime, timezone
from typing import get_args

import pytest
from pydantic import ValidationError

from src.domain.logic.clinicians.schema import (
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


def _clinician_create_kwargs(**overrides):
    """Minimum-valid kwargs for `ProviderCreate`.

    Location keys stay flat on the wire (form posts send
    ``location_city`` / ``location_state`` / ``location_zip`` at the
    top level — #451). The ``ProviderCreate`` schema's
    ``gather_flat_location`` pre-validator rolls them into the nested
    ``location`` value object before validation.
    """
    base = {
        "org_id": uuid.uuid4(),
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


def test_clinician_create_rejects_invalid_in_person_sessions():
    with pytest.raises(ValidationError):
        ProviderCreate(
            **_clinician_create_kwargs(in_person_sessions="maybe"),
        )


# --- extra="forbid" -----------------------------------------------------


def test_clinician_create_rejects_unknown_field():
    with pytest.raises(ValidationError):
        ProviderCreate(
            **_clinician_create_kwargs(),
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


def test_clinician_update_accepts_single_field():
    """Sanity check: setting one field is enough — the rule fires only
    when *every* field is `None`. Post-#451 ``location`` is itself a
    nested :class:`LocationPartial`; when no location subkey is
    supplied the field stays ``None`` (the gather pre-validator only
    creates the nested block when a flat ``location_<sub>`` key is
    present)."""
    new_org = uuid.uuid4()
    upd = ProviderUpdate(org_id=new_org)
    assert upd.org_id == new_org
    assert upd.location is None


# --- Create payload smoke tests -----------------------------------------


def test_clinician_create_requires_org_id():
    """``org_id`` is required on the wire (#524). Omitting it 422s."""
    kwargs = _clinician_create_kwargs()
    kwargs.pop("org_id")
    with pytest.raises(ValidationError):
        ProviderCreate(**kwargs)


def test_clinician_create_rejects_non_5_digit_zip():
    """Smoke test that the imported `ZipText` alias is wired up."""
    with pytest.raises(ValidationError):
        ProviderCreate(**_clinician_create_kwargs(location_zip="123"))


def test_clinician_create_defaults_to_oon_only():
    """Insurance posture defaults to OON-only: empty carrier list +
    `accepts_out_of_network=True`. The OON default reflects that most
    practices accept out-of-network; opting out is the explicit choice."""
    p = ProviderCreate(**_clinician_create_kwargs())
    assert p.accepts_out_of_network is True
    assert p.in_network_carriers == []
    assert p.sliding_scale is False
    assert p.cost is None


def test_clinician_create_with_in_network_carriers():
    """A non-empty carrier list expresses in-network acceptance — no
    separate boolean needed."""
    p = ProviderCreate(
        **_clinician_create_kwargs(
            in_network_carriers=["aetna", "cigna"],
        )
    )
    assert p.in_network_carriers == ["aetna", "cigna"]


def test_clinician_create_accepts_out_of_network_with_no_carriers():
    """OON-only is a valid posture: empty carrier list +
    `accepts_out_of_network=True`."""
    p = ProviderCreate(
        **_clinician_create_kwargs(
            accepts_out_of_network=True,
            in_network_carriers=[],
        )
    )
    assert p.accepts_out_of_network is True
    assert p.in_network_carriers == []


def test_clinician_create_rejects_unknown_carrier():
    with pytest.raises(ValidationError):
        ProviderCreate(
            **_clinician_create_kwargs(
                in_network_carriers=["not_a_real_carrier"],
            )
        )


def test_clinician_create_coerces_scalar_carrier_to_singleton_list():
    """HTML form posts collapse a 1-checkbox-checked group to a scalar;
    the shared `_scalar_to_list` BeforeValidator wraps that case before
    the `Literal[*INSURANCE_CARRIERS]` member check fires."""
    p = ProviderCreate(
        **_clinician_create_kwargs(
            in_network_carriers="aetna",
        )
    )
    assert p.in_network_carriers == ["aetna"]


def test_clinician_update_accepts_carrier_list_patch():
    """Patching only the carrier list is fine — no cross-field rule."""
    p = ProviderUpdate(in_network_carriers=["aetna"])
    assert p.in_network_carriers == ["aetna"]


def test_clinician_update_accepts_empty_carrier_list_patch():
    """Clearing the carrier list (setting to empty) is the patch shape
    for dropping in-network acceptance."""
    p = ProviderUpdate(in_network_carriers=[])
    assert p.in_network_carriers == []


# --- NPI validator ------------------------------------------------------


@pytest.mark.parametrize("npi", ["1234567890", "0000000000", "9999999999"])
def test_clinician_create_accepts_10_digit_npi(npi):
    p = ProviderCreate(**_clinician_create_kwargs(npi=npi))
    assert p.npi == npi


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_clinician_create_normalizes_blank_npi_to_none(blank):
    p = ProviderCreate(**_clinician_create_kwargs(npi=blank))
    assert p.npi is None


def test_clinician_create_omitted_npi_defaults_to_none():
    p = ProviderCreate(**_clinician_create_kwargs())
    assert p.npi is None


@pytest.mark.parametrize(
    "bad", ["123", "123456789", "12345678901", "12345abcde", "  123456 7890"]
)
def test_clinician_create_rejects_malformed_npi(bad):
    with pytest.raises(ValidationError):
        ProviderCreate(**_clinician_create_kwargs(npi=bad))


def test_clinician_update_accepts_npi_patch():
    p = ProviderUpdate(npi="1234567890")
    assert p.npi == "1234567890"


def test_clinician_update_rejects_malformed_npi():
    with pytest.raises(ValidationError):
        ProviderUpdate(npi="abc")


def test_clinician_read_round_trips_npi():
    """`ProviderRead.model_validate` carries `npi` through unchanged."""
    now = _now()
    pid = uuid.uuid4()
    p = ProviderRead.model_validate(
        {
            "id": pid,
            "owner_id": uuid.uuid4(),
            "created_at": now,
            "updated_at": now,
            "org_id": uuid.uuid4(),
            "org_name": "Sunrise",
            "npi": "1234567890",
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


def test_clinician_create_accepts_cost_and_sliding_scale():
    p = ProviderCreate(
        **_clinician_create_kwargs(
            sliding_scale=True,
            cost="$200 - $400 per session",
        )
    )
    assert p.sliding_scale is True
    assert p.cost == "$200 - $400 per session"


def test_insurance_carriers_labels_cover_all_tokens():
    """Every `INSURANCE_CARRIERS` token must have an entry in
    `INSURANCE_CARRIER_LABELS` so the form-render macro can resolve a
    label at request time. Mirrors the `test_labels_cover_their_tuples`
    guardrail in `test_post.py`."""
    assert set(INSURANCE_CARRIER_LABELS) == set(INSURANCE_CARRIERS)


def test_clinician_create_accepts_all_insurance_carriers():
    """Every token in `INSURANCE_CARRIERS` validates on the wire."""
    p = ProviderCreate(
        **_clinician_create_kwargs(
            in_network_carriers=list(INSURANCE_CARRIERS),
        )
    )
    assert p.in_network_carriers == list(INSURANCE_CARRIERS)


def test_clinician_create_accepts_nested_credential_lists():
    p = ProviderCreate(
        **_clinician_create_kwargs(),
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


def test_clinician_create_defaults_credential_lists_to_empty():
    p = ProviderCreate(**_clinician_create_kwargs())
    assert p.licensures == []
    assert p.educations == []
    assert p.certifications == []


# --- Solo practice path (#699) ------------------------------------------


def test_clinician_create_requires_org_id_without_solo_practice():
    """Without solo_practice=True, org_id is mandatory."""
    with pytest.raises(ValidationError):
        kwargs = _clinician_create_kwargs()
        del kwargs["org_id"]
        ProviderCreate(**kwargs)


def test_clinician_create_allows_missing_org_id_when_solo_practice():
    """solo_practice=True makes org_id optional at schema level."""
    kwargs = _clinician_create_kwargs()
    del kwargs["org_id"]
    p = ProviderCreate(**kwargs, solo_practice=True)
    assert p.solo_practice is True
    assert p.org_id is None


def test_clinician_create_solo_practice_excluded_from_model_dump():
    """solo_practice must not appear in model_dump() since it's handler-only."""
    p = ProviderCreate(**_clinician_create_kwargs(), solo_practice=True)
    dumped = p.model_dump()
    assert "solo_practice" not in dumped


# --- Read from nested dict ----------------------------------------------


def test_clinician_read_validates_from_nested_dict():
    """`ProviderRead.model_validate` should construct the nested
    sub-entity Read schemas without needing real ORM objects."""
    provider_id = uuid.uuid4()
    org_id = uuid.uuid4()
    now = _now()
    payload = {
        "id": provider_id,
        "owner_id": uuid.uuid4(),
        "created_at": now,
        "updated_at": now,
        "org_id": org_id,
        "org_name": "Sunrise",
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

    clinician = ProviderRead.model_validate(payload)

    assert clinician.org_name == "Sunrise"
    assert clinician.org_id == org_id
    assert len(clinician.licensures) == 1
    assert clinician.licensures[0].license_type == "lcsw"
    assert clinician.educations[0].month_completed == "2010-05"
    assert clinician.certifications[0].expiration_date is None


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
        (ProviderCreate, "in_person_sessions", LOCATION_AVAILABILITY_OPTIONS),
        (ProviderCreate, "virtual_sessions", LOCATION_AVAILABILITY_OPTIONS),
        (ProviderCreate, "in_network_carriers", INSURANCE_CARRIERS),
        # Update variants (Optional[Literal[*TUPLE]])
        (ProviderLicensureUpdate, "license_type", LICENSE_TYPES),
        (ProviderLicensureUpdate, "issuing_state", US_STATES),
        (ProviderEducationUpdate, "education_type", EDUCATION_TYPES),
        (ProviderCertificationUpdate, "certification_type", CERTIFICATION_TYPES),
        (ProviderUpdate, "in_person_sessions", LOCATION_AVAILABILITY_OPTIONS),
        # `ProviderUpdate.in_network_carriers` is
        # `list[Literal[*T]] | None`; the `_literal_args` helper doesn't
        # dig through the list-arm of the union, so the Create-variant
        # entry above is the lockstep guardrail for the carrier vocab.
        #
        # `location_state` moved into the :class:`Location` value object
        # in #451 — the `Location.state` lockstep test in
        # ``src/domain/logic/value_objects/test_location.py`` covers it
        # for every embedding schema at once.
    ],
)
def test_schema_literals_match_model_tuples(model_cls, field, expected):
    """Schema `Literal[*TUPLE]`s and DB CHECK universes must agree,
    sourced from the tuples in `src/domain/models/enums.py`. If you add or
    rename a vocabulary value, update both places (and the migration);
    this guardrail keeps them honest."""
    assert set(_literal_args(model_cls, field)) == set(expected)
