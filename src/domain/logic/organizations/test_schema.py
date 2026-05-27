"""Schema validation for `Organization` wire types.

The Read/Create/Update split mirrors the codebase's standard pattern;
the points worth pinning are: the `type` Literal is wired off
`ORGANIZATION_TYPES`, `WirePayload`'s extra-forbid covers `owner_id`
and `root_org_id` (server-controlled, must not be accepted on the
wire), and `PartialUpdate`'s at-least-one-field rule is in effect.
"""

import uuid

import pytest
from pydantic import ValidationError

from src.domain.logic.organizations.schema import (
    OrganizationCreate,
    OrganizationUpdate,
)
from src.domain.models.enums import ORGANIZATION_TYPES


def test_create_accepts_minimal_root():
    payload = OrganizationCreate(name="Acme Health", type="clinic")
    assert payload.name == "Acme Health"
    assert payload.type == "clinic"
    assert payload.parent_org_id is None


def test_create_accepts_parent_org_id():
    parent = uuid.uuid4()
    payload = OrganizationCreate(
        name="Acme Clinic", type="clinic", parent_org_id=parent
    )
    assert payload.parent_org_id == parent


def test_create_rejects_unknown_type():
    with pytest.raises(ValidationError):
        OrganizationCreate(name="Acme", type="not_a_real_type")


def test_create_rejects_owner_id_on_wire():
    """`owner_id` is server-derived from the requesting user — accepting
    it on the wire would let a client impersonate a different owner."""
    with pytest.raises(ValidationError):
        OrganizationCreate(name="Acme", type="clinic", owner_id=uuid.uuid4())


def test_create_rejects_root_org_id_on_wire():
    """`root_org_id` is server-derived via the parent chain — accepting
    it would let a client lie about the subtree root."""
    with pytest.raises(ValidationError):
        OrganizationCreate(name="Acme", type="clinic", root_org_id=uuid.uuid4())


def test_update_accepts_partial():
    payload = OrganizationUpdate(name="Renamed")
    assert payload.name == "Renamed"
    assert payload.type is None
    assert payload.parent_org_id is None


def test_update_rejects_empty_payload():
    """`PartialUpdate` requires at least one editable field set."""
    with pytest.raises(ValidationError):
        OrganizationUpdate()


def test_schema_type_literal_matches_enum_tuple():
    """Guardrail: every value in `ORGANIZATION_TYPES` is accepted by
    the `OrganizationCreate.type` Literal. Mirrors the clinician schema
    guardrail style."""
    for t in ORGANIZATION_TYPES:
        OrganizationCreate(name="x", type=t)
