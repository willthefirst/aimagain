"""Tests for `BaseRepository._list` and `BaseRepository._count`.

The primitives sit underneath every per-resource list method, so they're
exercised against a real session: in-memory SQLite with the same engine
fixture every other repo test uses. The other primitives (`_get_by_id`,
`_persist_new`, `_add_child`, `_patch`, `_delete`) are covered transitively
by the per-resource repo tests — this file specifically pins the list /
paginate / count contract.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import Provider, ProviderLicensure, User
from src.repositories.base import BaseRepository
from tests.helpers import create_test_user, make_provider, make_provider_licensure

pytestmark = pytest.mark.asyncio


async def _seed_users(
    session_manager: async_sessionmaker[AsyncSession],
    usernames: list[str],
) -> list[User]:
    """Persist users in the given order, return them in that order."""
    users = [create_test_user(username=name) for name in usernames]
    async with session_manager() as session:
        async with session.begin():
            for user in users:
                session.add(user)
    return users


# --- _list ----------------------------------------------------------------


async def test_list_returns_full_result_set_when_no_pagination(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    await _seed_users(db_test_session_manager, ["a", "b", "c"])

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        rows = await repo._list(select(User).order_by(User.username))

    assert [u.username for u in rows] == ["a", "b", "c"]


async def test_list_applies_limit(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    await _seed_users(db_test_session_manager, ["a", "b", "c", "d"])

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        rows = await repo._list(select(User).order_by(User.username), limit=2)

    assert [u.username for u in rows] == ["a", "b"]


async def test_list_applies_offset(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    await _seed_users(db_test_session_manager, ["a", "b", "c", "d"])

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        rows = await repo._list(select(User).order_by(User.username), offset=2)

    assert [u.username for u in rows] == ["c", "d"]


async def test_list_applies_offset_and_limit_together(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    await _seed_users(db_test_session_manager, ["a", "b", "c", "d", "e"])

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        rows = await repo._list(select(User).order_by(User.username), limit=2, offset=1)

    assert [u.username for u in rows] == ["b", "c"]


async def test_list_returns_empty_for_empty_table(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        rows = await repo._list(select(User))

    assert list(rows) == []


async def test_list_preserves_statement_order(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The statement's `order_by` is load-bearing — `_list` must not
    re-order or otherwise interfere with it."""
    await _seed_users(db_test_session_manager, ["c", "a", "b"])

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        asc = await repo._list(select(User).order_by(User.username.asc()))
        desc = await repo._list(select(User).order_by(User.username.desc()))

    assert [u.username for u in asc] == ["a", "b", "c"]
    assert [u.username for u in desc] == ["c", "b", "a"]


# --- _count ---------------------------------------------------------------


async def test_count_empty_returns_zero(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        total = await repo._count(select(User))

    assert total == 0


async def test_count_single_row(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    await _seed_users(db_test_session_manager, ["only"])

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        total = await repo._count(select(User))

    assert total == 1


async def test_count_multi_row(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    await _seed_users(db_test_session_manager, ["a", "b", "c", "d"])

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        total = await repo._count(select(User))

    assert total == 4


async def test_count_respects_filters(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    users = await _seed_users(db_test_session_manager, ["a", "b", "c"])
    target = users[0]

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        total = await repo._count(select(User).filter(User.id != target.id))

    assert total == 2


async def test_count_respects_distinct_with_join(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`.distinct()` is load-bearing for `list_providers` — when a parent
    has multiple matching child rows, the count must reflect distinct
    parents, not the join's cardinality."""
    owner = create_test_user(username=f"owner-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)

    provider = make_provider(owner_id=owner.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)

    # Two licensures matching `license_type='lcsw'` on the same provider.
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                make_provider_licensure(
                    provider_id=provider.id,
                    license_type="lcsw",
                    license_number="L-1",
                )
            )
            session.add(
                make_provider_licensure(
                    provider_id=provider.id,
                    license_type="lcsw",
                    license_number="L-2",
                )
            )

    stmt = (
        select(Provider)
        .join(ProviderLicensure, ProviderLicensure.provider_id == Provider.id)
        .filter(ProviderLicensure.license_type == "lcsw")
        .distinct()
    )

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        total = await repo._count(stmt)
        # Sanity: _list returns one distinct row too.
        rows = await repo._list(stmt)

    assert total == 1
    assert len(rows) == 1
