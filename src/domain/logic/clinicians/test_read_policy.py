"""Tests for the provider-network capability predicate as it relates to
the Clinician entity.

`CLINICIAN_ENTITY` no longer carries a `read_policy` — the directory is
reachable for every authenticated viewer, with identifying rows redacted
per-row at render time when the viewer lacks network access and isn't
the owner (see `_clinician_card.html` / `clinicians/detail.html`).

The predicate (`assert_can_access_network`) is still exercised here
because it drives the template-side redaction flag, and the data-layer
guard mechanism remains a framework feature any future entity may opt
into.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.capabilities import (
    assert_can_access_network,
)
from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.specs.clinician import CLINICIAN_ENTITY
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


def test_clinician_entity_declares_no_read_policy():
    """Structural pin: CLINICIAN_ENTITY no longer carries a `read_policy`.

    The provider-network gate moved from a binary data-layer guard to
    per-row template redaction so the viewer can still see and self-
    manage their own clinician rows before clearing network
    verification. Other identifying rows are replaced with
    `locked_name` / `locked_field` placeholders.
    """
    assert CLINICIAN_ENTITY.read_policy is None


# --- Repository-layer guard enforcement ---------------------------------------
# The mechanism (`_read_guard` stamped on a BaseRepository instance) is
# preserved at the framework level for future entities; pin it here once
# against ClinicianRepository so any regression in the guard's wiring is
# caught alongside the clinician-spec changes.


@pytest.mark.asyncio
async def test_repo_guard_blocks_list_for_unverified_user_when_attached(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """When the guard IS stamped on the repo, `list_for_user` raises for
    an unverified user. Clinician routes no longer attach this guard, but
    the mechanism stays intact for any spec that opts in via `read_policy`.
    """
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
async def test_repo_guard_allows_superuser(
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
