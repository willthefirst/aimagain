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

from src.domain.models import Provider, ProviderLicensure, User
from src.framework.persistence.base_repository import BaseRepository
from tests.helpers import (
    create_test_user,
    make_provider_licensure,
    make_provider_with_org,
)

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

    provider = make_provider_with_org(owner_id=owner.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)
        await session.refresh(provider)
        clinician_id = provider.clinician_id

    # Two licensures matching `license_type='lcsw'` on the same provider.
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                make_provider_licensure(
                    clinician_id=clinician_id,
                    license_type="lcsw",
                    license_number="L-1",
                )
            )
            session.add(
                make_provider_licensure(
                    clinician_id=clinician_id,
                    license_type="lcsw",
                    license_number="L-2",
                )
            )

    stmt = (
        select(Provider)
        .join(
            ProviderLicensure, ProviderLicensure.clinician_id == Provider.clinician_id
        )
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


# --- list_default ---------------------------------------------------------


async def test_list_default_orders_by_column(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`list_default` honors the `order_by` argument exactly. Specs pass
    `User.username` / `Post.created_at.desc()` / etc. — whatever the
    entity needs."""
    await _seed_users(db_test_session_manager, ["c", "a", "b"])

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        rows = await repo.list_default(User, order_by=User.username)

    assert [u.username for u in rows] == ["a", "b", "c"]


async def test_list_default_exclude_self_filters_target_user(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`exclude_self` drops the row whose id matches `exclude_self.id`.
    The viewer-filtering pattern `handle_list` uses for entities with
    `spec.list_exclude_self=True`."""
    users = await _seed_users(db_test_session_manager, ["a", "b", "c"])
    viewer = users[0]

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        rows = await repo.list_default(
            User, order_by=User.username, exclude_self=viewer
        )

    assert [u.username for u in rows] == ["b", "c"]


async def test_list_default_none_exclude_self_returns_everyone(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`exclude_self=None` (the default) skips the filter — anonymous
    viewers see every row."""
    await _seed_users(db_test_session_manager, ["a", "b"])

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        rows = await repo.list_default(User, order_by=User.username)

    assert len(rows) == 2


# --- list_owned_by --------------------------------------------------------


async def test_list_owned_by_returns_only_rows_owned_by_user(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`list_owned_by` filters by `owner_id` — rows owned by a
    different user are excluded."""
    owner = await _seed_users(db_test_session_manager, ["owner"])
    other = await _seed_users(db_test_session_manager, ["other"])
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(make_provider_with_org(owner_id=owner[0].id))
            session.add(make_provider_with_org(owner_id=other[0].id))

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        rows = await repo.list_owned_by(Provider, owner[0].id)

    assert len(rows) == 1
    assert rows[0].owner_id == owner[0].id


async def test_list_owned_by_orders_newest_first(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`list_owned_by` orders by `created_at` descending. Set
    `created_at` explicitly to force a deterministic ordering — SQLite's
    server-default `CURRENT_TIMESTAMP` is second-precision and rows
    inserted in the same second would tie."""
    from datetime import datetime, timedelta, timezone

    owner = await _seed_users(db_test_session_manager, ["owner"])
    earlier = datetime.now(timezone.utc)
    later = earlier + timedelta(seconds=1)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                make_provider_with_org(
                    owner_id=owner[0].id,
                    practice_name="First",
                    created_at=earlier,
                )
            )
            session.add(
                make_provider_with_org(
                    owner_id=owner[0].id,
                    practice_name="Second",
                    created_at=later,
                )
            )

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        rows = await repo.list_owned_by(Provider, owner[0].id)

    assert [p.org.name for p in rows] == ["Second", "First"]


async def test_list_owned_by_honors_offset_and_limit(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`offset` and `limit` flow through to `_list`."""
    from datetime import datetime, timedelta, timezone

    owner = await _seed_users(db_test_session_manager, ["owner"])
    base = datetime.now(timezone.utc)

    async with db_test_session_manager() as session:
        async with session.begin():
            for i, name in enumerate(["A", "B", "C", "D"]):
                session.add(
                    make_provider_with_org(
                        owner_id=owner[0].id,
                        practice_name=name,
                        created_at=base + timedelta(seconds=i),
                    )
                )

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        rows = await repo.list_owned_by(Provider, owner[0].id, offset=1, limit=2)

    # Newest first: D, C, B, A — offset=1 limit=2 → C, B.
    assert [p.org.name for p in rows] == ["C", "B"]


async def test_list_owned_by_empty_when_user_owns_nothing(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner = await _seed_users(db_test_session_manager, ["owner"])

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        rows = await repo.list_owned_by(Provider, owner[0].id)

    assert list(rows) == []
