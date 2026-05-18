"""Schema validation for `Program` wire types.

The Read/Create/Update split mirrors the codebase's standard pattern;
the points worth pinning are: the ``state_preference`` Literal is
wired off :data:`US_STATES`, ``WirePayload``'s extra-forbid covers
``owner_id`` (server-controlled, must not be accepted on the wire),
and ``PartialUpdate``'s at-least-one-field rule is in effect.
"""

import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from src.domain.logic.programs.schema import (
    ProgramCreate,
    ProgramUpdate,
)


def _create_kwargs(**overrides):
    base = dict(org_id=uuid.uuid4(), name="RISE IOP")
    return {**base, **overrides}


def test_create_accepts_minimal():
    org_id = uuid.uuid4()
    payload = ProgramCreate(org_id=org_id, name="RISE IOP")
    assert payload.org_id == org_id
    assert payload.name == "RISE IOP"
    # Defaults populated.
    assert payload.accepting_referrals is True
    assert payload.state_preference is None
    assert payload.description is None


def test_create_strips_name():
    payload = ProgramCreate(org_id=uuid.uuid4(), name="  RISE IOP  ")
    assert payload.name == "RISE IOP"


def test_create_rejects_empty_name():
    with pytest.raises(ValidationError):
        ProgramCreate(org_id=uuid.uuid4(), name="   ")


def test_create_accepts_us_state_preference():
    payload = ProgramCreate(**_create_kwargs(state_preference="CA"))
    assert payload.state_preference == "CA"


def test_create_rejects_unknown_state_preference():
    with pytest.raises(ValidationError):
        ProgramCreate(**_create_kwargs(state_preference="ZZ"))


def test_create_accepts_dates():
    payload = ProgramCreate(
        **_create_kwargs(start_date=date(2026, 5, 1), end_date=date(2026, 8, 1))
    )
    assert payload.start_date == date(2026, 5, 1)
    assert payload.end_date == date(2026, 8, 1)


def test_create_rejects_owner_id_on_wire():
    """``owner_id`` is server-derived from the requesting user — accepting
    it on the wire would let a client impersonate a different owner."""
    with pytest.raises(ValidationError):
        ProgramCreate(**_create_kwargs(owner_id=uuid.uuid4()))


def test_update_at_least_one_field_required():
    with pytest.raises(ValidationError):
        ProgramUpdate()


def test_update_accepts_single_field():
    payload = ProgramUpdate(name="Renamed")
    assert payload.name == "Renamed"


def test_update_org_id_accepted():
    new_org = uuid.uuid4()
    payload = ProgramUpdate(org_id=new_org)
    assert payload.org_id == new_org


def test_update_rejects_unknown_state_preference():
    with pytest.raises(ValidationError):
        ProgramUpdate(state_preference="ZZ")
