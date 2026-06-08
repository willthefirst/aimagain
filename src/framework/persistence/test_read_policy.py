"""Tests for `BaseRepository._check_read` and the ReadPolicy guard contract.

The guard fires on `_list` and `_count` (bulk-read paths). It is intentionally
NOT on `_get_by_id` — that primitive is used by both display and mutation
paths; guarding it blocks owners from editing their own records.

The guard is a no-op when no user or no guard is present (background tasks,
direct test instantiation).
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import User
from src.framework.http.exceptions import ForbiddenError
from src.framework.persistence.base_repository import BaseRepository
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio


def _always_deny(user: object) -> None:
    raise ForbiddenError(detail="denied by test guard")


def _always_allow(user: object) -> None:
    pass


async def _seed_user(session_manager: async_sessionmaker[AsyncSession]) -> User:
    user = create_test_user(username="target")
    async with session_manager() as session:
        async with session.begin():
            session.add(user)
    return user


# --- No guard set (open by default) ------------------------------------------


async def test_list_no_guard_succeeds(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        rows = await repo._list(select(User))
    assert len(rows) == 1


async def test_get_by_id_no_guard_succeeds(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """_get_by_id is intentionally unguarded (used by mutation paths too)."""
    user = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        row = await repo._get_by_id(User, user.id)
    assert row is not None


async def test_count_no_guard_succeeds(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        count = await repo._count(select(User))
    assert count == 1


# --- Guard set, no user (background-task bypass) ------------------------------


async def test_list_guard_no_user_is_noop(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """When _requesting_user is None the guard must not fire — background
    tasks and test helpers that create repos without a user must stay open."""
    await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        repo._read_guard = _always_deny
        rows = await repo._list(select(User))
    assert len(rows) == 1


# --- Guard set, user present, guard denies ------------------------------------


async def test_list_guard_denies_raises(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    requester = create_test_user(username="requester")
    await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        repo._requesting_user = requester
        repo._read_guard = _always_deny
        with pytest.raises(ForbiddenError):
            await repo._list(select(User))


async def test_get_by_id_with_guard_still_succeeds(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """_get_by_id bypasses the guard — mutation paths (update/delete) use
    this to load the target before ownership checks run."""
    requester = create_test_user(username="requester")
    user = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        repo._requesting_user = requester
        repo._read_guard = _always_deny
        row = await repo._get_by_id(User, user.id)
    assert row is not None


async def test_count_guard_denies_raises(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    requester = create_test_user(username="requester")
    await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        repo._requesting_user = requester
        repo._read_guard = _always_deny
        with pytest.raises(ForbiddenError):
            await repo._count(select(User))


# --- Guard set, user present, guard allows ------------------------------------


async def test_list_guard_allows_succeeds(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    requester = create_test_user(username="requester")
    await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        repo._requesting_user = requester
        repo._read_guard = _always_allow
        rows = await repo._list(select(User))
    assert len(rows) == 1
