"""Tests for clinician read_policy: provider-network capability gate.

The guard fires at the repository layer regardless of whether the route
handler performs its own capability check. These tests attach the guard
directly (mirroring what the EntitySpec.read_policy dep wrapper does at
request time) and verify the data-layer enforcement.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.capabilities import (
    assert_can_access_network,
    can_access_network,
)
from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.specs.clinician import CLINICIAN_ENTITY
from src.framework.dispatch.entity_spec import ReadPolicy
from src.framework.http.exceptions import ForbiddenError
from tests.helpers import create_test_user, make_clinician_with_org


def _unverified_user():
    """User with no verified claim: no clinician, no org rep, email unverified."""
    return create_test_user(username="unverified", is_verified=False)


def _email_only_user():
    """User with verified email but no clinician/org-rep claim."""
    return create_test_user(username="email_only", is_verified=True)


def _superuser():
    return create_test_user(username="admin", is_superuser=True)


# --- assert_can_access_network unit -------------------------------------------


def test_assert_denies_unverified_user():
    user = _unverified_user()
    with pytest.raises(ForbiddenError):
        assert_can_access_network(user)


def test_assert_denies_email_only_user():
    user = _email_only_user()
    with pytest.raises(ForbiddenError):
        assert_can_access_network(user)


def test_assert_allows_superuser():
    """Superusers bypass the capability check regardless of claim state."""
    user = _superuser()
    assert_can_access_network(user)  # must not raise


def test_clinician_entity_declares_provider_network_read_policy():
    """Structural pin: CLINICIAN_ENTITY must carry a ReadPolicy so new routes
    and route modifications benefit from the data-layer guard automatically."""
    assert CLINICIAN_ENTITY.read_policy is not None
    assert isinstance(CLINICIAN_ENTITY.read_policy, ReadPolicy)
    assert CLINICIAN_ENTITY.read_policy.assert_can_read is assert_can_access_network
    assert CLINICIAN_ENTITY.read_policy.can_read is can_access_network


# --- Repository-layer guard enforcement ---------------------------------------


@pytest.mark.asyncio
async def test_clinician_list_blocked_for_unverified_user(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """When the guard is stamped on the repo (as the dep wrapper does at
    request time), list_for_user raises ForbiddenError for an unverified user."""
    owner = create_test_user(username="owner", is_verified=True)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            clin = make_clinician_with_org(owner_id=owner.id)
            session.add(clin)

    requester = _unverified_user()
    async with db_test_session_manager() as session:
        repo = ClinicianRepository(session)
        repo._requesting_user = requester
        repo._read_guard = assert_can_access_network
        with pytest.raises(ForbiddenError):
            await repo.list_for_user(owner.id)


@pytest.mark.asyncio
async def test_clinician_get_by_id_not_blocked_for_unverified_user(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """_get_by_id intentionally bypasses the guard so owners can still
    load their own profile for update/delete flows before claim verification."""
    owner = create_test_user(username="owner2", is_verified=True)
    clin_id = None
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            clin = make_clinician_with_org(owner_id=owner.id)
            session.add(clin)
            await session.flush()
            clin_id = clin.id

    requester = _unverified_user()
    async with db_test_session_manager() as session:
        repo = ClinicianRepository(session)
        repo._requesting_user = requester
        repo._read_guard = assert_can_access_network
        from src.domain.models import Clinician

        row = await repo._get_by_id(Clinician, clin_id)
        assert row is not None


@pytest.mark.asyncio
async def test_clinician_list_allowed_for_superuser(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Superusers bypass the guard and receive data normally."""
    owner = create_test_user(username="owner3", is_verified=True)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            clin = make_clinician_with_org(owner_id=owner.id)
            session.add(clin)

    admin = _superuser()
    async with db_test_session_manager() as session:
        repo = ClinicianRepository(session)
        repo._requesting_user = admin
        repo._read_guard = assert_can_access_network
        rows = await repo.list_for_user(owner.id)
    assert len(rows) == 1
