"""Schema tests for the ClinicianAffiliation wire layer.

The schemas mirror the per-role fields on `ClinicianCreate`; these
tests pin the wire contract (flat-location round-trip, Literal
validation against the enum tuples, scalar→list coercion for the
multi-checkbox carriers field).
"""

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.domain.logic.clinician_affiliations.schema import (
    ClinicianAffiliationCreate,
    ClinicianAffiliationRead,
    ClinicianAffiliationUpdate,
)


def _wire_create(**overrides):
    base = dict(
        org_id=uuid.uuid4(),
        location_city="Brooklyn",
        location_state="NY",
        location_zip="11201",
        in_person_sessions="yes",
        virtual_sessions="no",
        accepts_out_of_network=True,
        in_network_carriers=["aetna", "anthem_bcbs"],
        sliding_scale=False,
        cost="$200/session",
    )
    base.update(overrides)
    return base


def test_create_accepts_flat_location_and_dumps_flat():
    """Flat ``location_city`` / ``location_state`` / ``location_zip``
    in, flat keys out — the value object stays an in-Python detail."""
    payload = ClinicianAffiliationCreate(**_wire_create())
    dumped = payload.model_dump()
    assert dumped["location_city"] == "Brooklyn"
    assert dumped["location_state"] == "NY"
    assert dumped["location_zip"] == "11201"
    assert "location" not in dumped


def test_create_rejects_non_us_state():
    """`location_state` is a `Literal[*US_STATES]` via the Location
    value object — non-US states 422."""
    with pytest.raises(ValidationError):
        ClinicianAffiliationCreate(**_wire_create(location_state="ZZ"))


def test_create_rejects_unknown_session_value():
    """`in_person_sessions` validates against LOCATION_AVAILABILITY_OPTIONS."""
    with pytest.raises(ValidationError):
        ClinicianAffiliationCreate(**_wire_create(in_person_sessions="maybe"))


def test_create_accepts_solo_practice_with_no_org():
    """Solo practice (#1311): `org_id` blank → coerced to None →
    affiliation row created with no organizational entity. Location and
    sessions can also be omitted (user fills them in later via the
    row's own PATCH). The minimum body is empty."""
    payload = ClinicianAffiliationCreate()
    assert payload.org_id is None
    assert payload.location is None
    assert payload.in_person_sessions is None
    assert payload.virtual_sessions is None
    # NOT NULL columns get their default values so the row inserts
    # cleanly even on an empty body.
    assert payload.accepts_out_of_network is True
    assert payload.in_network_carriers == []
    assert payload.sliding_scale is False


def test_create_accepts_partial_location():
    """`location` is now a `LocationPartial` — a single subfield can be
    set without the others. Mirrors how the inline add-practice form
    behaves when the user only fills in the city."""
    payload = ClinicianAffiliationCreate(location_city="Brooklyn")
    assert payload.location is not None
    assert payload.location.city == "Brooklyn"
    assert payload.location.state is None
    assert payload.location.zip is None


def test_create_coerces_blank_org_id_to_none():
    """The form posts `org_id=` (empty string) when the user picks the
    "(Solo practice)" option. `WirePayload`'s blank-string coercion
    turns that into `None` before per-field validation, so the wire
    edge is honest about the solo case."""
    payload = ClinicianAffiliationCreate(org_id="")
    assert payload.org_id is None


def test_create_coerces_scalar_carrier_to_list():
    """A single-checkbox-checked group arrives as a scalar; the schema
    wraps it in a one-element list so the `Literal[*INSURANCE_CARRIERS]`
    member check fires once."""
    payload = ClinicianAffiliationCreate(**_wire_create(in_network_carriers="aetna"))
    assert payload.in_network_carriers == ["aetna"]


def test_update_is_partial():
    """`ClinicianAffiliationUpdate` only requires the fields the caller actually
    sets — every field defaults to `None`."""
    payload = ClinicianAffiliationUpdate(sliding_scale=True)
    dumped = payload.model_dump(exclude_unset=True)
    assert dumped == {"sliding_scale": True}


# --- Steady-state profile (#1358 PR-f, parent-schema extension) --------


def test_create_defaults_steady_state_profile_to_empty():
    """Multi-selects default to `[]`; free-text fields to `None`.
    Mirrors `ProgramCreate`."""
    payload = ClinicianAffiliationCreate()
    assert payload.services == []
    assert payload.settings == []
    assert payload.modalities == []
    assert payload.age_groups == []
    assert payload.genders == []
    assert payload.website is None
    assert payload.referral_instructions is None


def test_create_accepts_steady_state_profile():
    payload = ClinicianAffiliationCreate(
        services=["psychotherapy", "medication_management"],
        settings=["outpatient"],
        modalities=["dbt", "emdr"],
        age_groups=["adults_25_64"],
        genders=["female"],
        website="https://example.com",
        referral_instructions="Email intake@example.com.",
    )
    assert payload.services == ["psychotherapy", "medication_management"]
    assert payload.settings == ["outpatient"]
    assert payload.modalities == ["dbt", "emdr"]
    assert payload.age_groups == ["adults_25_64"]
    assert payload.genders == ["female"]
    assert payload.website == "https://example.com"
    assert payload.referral_instructions == "Email intake@example.com."


def test_create_normalizes_scalar_service_to_list():
    payload = ClinicianAffiliationCreate(services="psychotherapy")
    assert payload.services == ["psychotherapy"]


def test_create_rejects_unknown_service():
    with pytest.raises(ValidationError):
        ClinicianAffiliationCreate(services=["not_a_service"])


def test_create_strips_blank_website_to_none():
    payload = ClinicianAffiliationCreate(website="   ")
    assert payload.website is None


def test_create_rejects_currently_accepting_new_patients_on_create():
    """`currently_accepting_new_patients` is a server-managed cache
    (toggled by OpeningDetail lifecycle handlers) and intentionally not
    on the Create surface."""
    with pytest.raises(ValidationError, match="extra"):
        ClinicianAffiliationCreate(currently_accepting_new_patients=True)


def test_create_rejects_languages():
    """`languages` is person-level (lives on `Clinician`), not
    per-affiliation — model contract; the wire must reject it here."""
    with pytest.raises(ValidationError, match="extra"):
        ClinicianAffiliationCreate(languages=["en"])


def test_update_accepts_steady_state_field():
    payload = ClinicianAffiliationUpdate(services=["psychotherapy"])
    assert payload.services == ["psychotherapy"]


def test_update_accepts_empty_list_to_clear():
    """List-valued PATCH replaces the whole list; `[]` clears."""
    payload = ClinicianAffiliationUpdate(services=[])
    assert payload.services == []


def test_update_rejects_unknown_modality():
    with pytest.raises(ValidationError):
        ClinicianAffiliationUpdate(modalities=["not_a_modality"])


def test_update_rejects_currently_accepting_new_patients():
    """Same server-managed-cache rationale as Create."""
    with pytest.raises(ValidationError, match="extra"):
        ClinicianAffiliationUpdate(currently_accepting_new_patients=True)


def test_read_defaults_steady_state_profile_to_empty():
    """A row with no explicit steady-state values reads as `[]`/`None`,
    matching the columns' server-side defaults. The `bool` field
    `currently_accepting_new_patients` defaults to `False`."""

    class _Fake:
        id = uuid.uuid4()
        clinician_id = uuid.uuid4()
        org_id = None
        created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        updated_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
        location_city = None
        location_state = None
        location_zip = None
        in_person_sessions = None
        virtual_sessions = None
        accepts_out_of_network = True
        in_network_carriers = []
        sliding_scale = False
        cost = None
        services = []
        settings = []
        modalities = []
        age_groups = []
        genders = []
        website = None
        referral_instructions = None
        currently_accepting_new_patients = False

    read = ClinicianAffiliationRead.model_validate(_Fake(), from_attributes=True)
    assert read.services == []
    assert read.settings == []
    assert read.modalities == []
    assert read.age_groups == []
    assert read.genders == []
    assert read.website is None
    assert read.referral_instructions is None
    assert read.currently_accepting_new_patients is False


def test_read_round_trips_steady_state_profile():
    class _Fake:
        id = uuid.uuid4()
        clinician_id = uuid.uuid4()
        org_id = uuid.uuid4()
        created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        updated_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
        location_city = None
        location_state = None
        location_zip = None
        in_person_sessions = None
        virtual_sessions = None
        accepts_out_of_network = True
        in_network_carriers = []
        sliding_scale = False
        cost = None
        services = ["psychotherapy"]
        settings = ["outpatient"]
        modalities = ["dbt"]
        age_groups = ["adults_25_64"]
        genders = ["female"]
        website = "https://example.com"
        referral_instructions = "Email intake@example.com."
        currently_accepting_new_patients = True

    read = ClinicianAffiliationRead.model_validate(_Fake(), from_attributes=True)
    assert read.services == ["psychotherapy"]
    assert read.settings == ["outpatient"]
    assert read.modalities == ["dbt"]
    assert read.age_groups == ["adults_25_64"]
    assert read.genders == ["female"]
    assert read.website == "https://example.com"
    assert read.referral_instructions == "Email intake@example.com."
    assert read.currently_accepting_new_patients is True


def test_read_roundtrips_from_attribute_object():
    """`ClinicianAffiliationRead` reads through Pydantic's `from_attributes`
    path — it has to handle a flat ORM-style object (city/state/zip
    as attributes, not nested under `location`)."""

    class _Fake:
        id = uuid.uuid4()
        clinician_id = uuid.uuid4()
        clinician_id = uuid.uuid4()
        org_id = uuid.uuid4()
        created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        updated_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
        location_city = "Brooklyn"
        location_state = "NY"
        location_zip = "11201"
        in_person_sessions = "yes"
        virtual_sessions = "no"
        accepts_out_of_network = True
        in_network_carriers = ["aetna"]
        sliding_scale = False
        cost = None

    read = ClinicianAffiliationRead.model_validate(_Fake(), from_attributes=True)
    dumped = read.model_dump()
    assert dumped["location_city"] == "Brooklyn"
    assert dumped["in_network_carriers"] == ["aetna"]
