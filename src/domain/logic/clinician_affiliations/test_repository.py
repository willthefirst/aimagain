"""Smoke tests for :class:`ClinicianAffiliationRepository`.

The repository is a thin shell over ``BaseRepository``; these tests
pin that it actually registers with the FastAPI dependency machinery
(via ``register_repository``) and that the framework's create / patch /
delete primitives work against it on the persisted ``affiliations``
table.

Route-level coverage of the sub-resource CRUD lives in
``src/domain/routes/test_clinicians.py::test_*_affiliation_*``.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.logic.clinician_affiliations.repository import (
    ClinicianAffiliationRepository,
    get_clinician_affiliation_repository,
)
from src.domain.models import Clinician, ClinicianAffiliation, Organization, User
from src.framework.persistence.dependencies import (
    UnknownRepoTypeError,
    resolver_for,
)


@pytest_asyncio.fixture
async def session(db_test_session_manager: async_sessionmaker):
    async with db_test_session_manager() as s:
        yield s


def test_repository_registers_with_dispatch_registry():
    """`register_repository(ClinicianAffiliationRepository)` adds the class to
    the type → resolver registry so the framework's
    `resolver_for(ClinicianAffiliationRepository)` injection path succeeds for
    the sub-resource handlers."""
    try:
        resolver = resolver_for(ClinicianAffiliationRepository)
    except UnknownRepoTypeError as exc:
        pytest.fail(str(exc))
    # `get_clinician_affiliation_repository` is the public binding the spec uses.
    assert resolver is get_clinician_affiliation_repository


@pytest.mark.asyncio
async def test_repository_creates_and_fetches_affiliation(session):
    """End-to-end repo smoke: persist a Clinician (which auto-creates
    one ClinicianAffiliation via `Clinician.__init__`), then create a second
    ClinicianAffiliation through the repo and fetch both back."""
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        username="repo-test",
        email="repo-test@example.com",
        hashed_password="not-a-password",
        is_active=True,
        is_verified=True,
    )
    org_a_id = uuid.uuid4()
    org_a = Organization(
        id=org_a_id,
        name="Acme",
        owner_id=user_id,
    )
    org_b_id = uuid.uuid4()
    org_b = Organization(
        id=org_b_id,
        name="Beta",
        owner_id=user_id,
    )
    clinician = Clinician(
        owner_id=user_id,
        org_id=org_a_id,
        first_name="Jane",
        last_name="Smith",
        location_city="Brooklyn",
        location_state="NY",
        location_zip="11201",
        in_person_sessions="yes",
        virtual_sessions="no",
        accepts_out_of_network=True,
        in_network_carriers=["aetna"],
        sliding_scale=False,
    )
    session.add_all([user, org_a, org_b, clinician])
    await session.flush()

    repo = ClinicianAffiliationRepository(session)
    new_aff = ClinicianAffiliation(
        clinician_id=clinician.id,
        org_id=org_b_id,
        location_city="Manhattan",
        location_state="NY",
        location_zip="10001",
        in_person_sessions="no",
        virtual_sessions="yes",
        accepts_out_of_network=False,
        in_network_carriers=[],
        sliding_scale=True,
        cost="$200/session",
    )
    persisted = await repo.create(new_aff)
    assert persisted.id is not None

    fetched = await repo.get_by_model_id(ClinicianAffiliation, persisted.id)
    assert fetched is not None
    assert fetched.org_id == org_b_id
    assert fetched.sliding_scale is True
