"""Schema validation for `Organization` wire types.

`WirePayload`'s extra-forbid keeps server-controlled fields off the
wire, `PartialUpdate`'s at-least-one-field rule is in effect, and NPI
is required on create.
"""

import uuid

import pytest
from pydantic import ValidationError

from src.domain.logic.organizations.schema import (
    OrganizationCreate,
    OrganizationUpdate,
)


def test_create_accepts_minimal_payload():
    payload = OrganizationCreate(name="Acme Health", npi="1234567890")
    assert payload.name == "Acme Health"
    assert payload.npi == "1234567890"


def test_create_requires_npi():
    with pytest.raises(ValidationError):
        OrganizationCreate(name="Acme Health")


def test_create_rejects_blank_npi():
    with pytest.raises(ValidationError):
        OrganizationCreate(name="Acme Health", npi="")


def test_create_rejects_owner_id_on_wire():
    """`owner_id` is server-derived from the requesting user — accepting
    it on the wire would let a client impersonate a different owner."""
    with pytest.raises(ValidationError):
        OrganizationCreate(name="Acme", npi="1234567890", owner_id=uuid.uuid4())


def test_update_accepts_partial():
    payload = OrganizationUpdate(name="Renamed")
    assert payload.name == "Renamed"


def test_update_rejects_empty_payload():
    """`PartialUpdate` requires at least one editable field set."""
    with pytest.raises(ValidationError):
        OrganizationUpdate()
