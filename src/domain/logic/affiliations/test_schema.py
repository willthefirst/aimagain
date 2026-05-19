"""Schema tests for the Affiliation wire layer.

The schemas mirror the per-role fields on `ProviderCreate`; these
tests pin the wire contract (flat-location round-trip, Literal
validation against the enum tuples, scalar→list coercion for the
multi-checkbox carriers field).
"""

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.domain.logic.affiliations.schema import (
    AffiliationCreate,
    AffiliationRead,
    AffiliationUpdate,
)


def _wire_create(**overrides):
    base = dict(
        org_id=uuid.uuid4(),
        location_city="Brooklyn",
        location_state="NY",
        location_zip="11201",
        in_person_sessions="yes",
        virtual_sessions="please_contact",
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
    payload = AffiliationCreate(**_wire_create())
    dumped = payload.model_dump()
    assert dumped["location_city"] == "Brooklyn"
    assert dumped["location_state"] == "NY"
    assert dumped["location_zip"] == "11201"
    assert "location" not in dumped


def test_create_rejects_non_us_state():
    """`location_state` is a `Literal[*US_STATES]` via the Location
    value object — non-US states 422."""
    with pytest.raises(ValidationError):
        AffiliationCreate(**_wire_create(location_state="ZZ"))


def test_create_rejects_unknown_session_value():
    """`in_person_sessions` validates against LOCATION_AVAILABILITY_OPTIONS."""
    with pytest.raises(ValidationError):
        AffiliationCreate(**_wire_create(in_person_sessions="maybe"))


def test_create_coerces_scalar_carrier_to_list():
    """A single-checkbox-checked group arrives as a scalar; the schema
    wraps it in a one-element list so the `Literal[*INSURANCE_CARRIERS]`
    member check fires once."""
    payload = AffiliationCreate(**_wire_create(in_network_carriers="aetna"))
    assert payload.in_network_carriers == ["aetna"]


def test_update_is_partial():
    """`AffiliationUpdate` only requires the fields the caller actually
    sets — every field defaults to `None`."""
    payload = AffiliationUpdate(sliding_scale=True)
    dumped = payload.model_dump(exclude_unset=True)
    assert dumped == {"sliding_scale": True}


def test_read_roundtrips_from_attribute_object():
    """`AffiliationRead` reads through Pydantic's `from_attributes`
    path — it has to handle a flat ORM-style object (city/state/zip
    as attributes, not nested under `location`)."""

    class _Fake:
        id = uuid.uuid4()
        provider_id = uuid.uuid4()
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

    read = AffiliationRead.model_validate(_Fake(), from_attributes=True)
    dumped = read.model_dump()
    assert dumped["location_city"] == "Brooklyn"
    assert dumped["in_network_carriers"] == ["aetna"]
