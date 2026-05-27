"""Tests for `UserFavoriteRepository`.

Exercises CRUD on the M:N edge plus the listing join. Idempotency is
*not* enforced here — the repo lets the unique constraint speak; the
logic layer is responsible for `get_by_pair` before `add_favorite`. This
test file pins the listing's newest-first ordering and the `is_favorited`
truth table.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.favorites.repository import UserFavoriteRepository
from src.domain.models import User, UserFavorite
from tests.helpers import create_test_user, make_clinician_with_org

pytestmark = pytest.mark.asyncio


async def _seed_user(
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> User:
    user = create_test_user(username=f"fav-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
    return user


async def _seed_provider(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    practice_name: str = "Acme Health",
):
    owner = create_test_user(username=f"owner-{uuid.uuid4()}")
    provider = make_clinician_with_org(owner_id=owner.id, practice_name=practice_name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            session.add(provider)
    return provider


async def test_add_favorite_persists_edge(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    provider = await _seed_provider(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        edge = await repo.add_favorite(user_id=user.id, clinician_id=provider.id)
        await session.commit()
        edge_id = edge.id

    async with db_test_session_manager() as session:
        row = (
            (
                await session.execute(
                    select(UserFavorite).filter(UserFavorite.id == edge_id)
                )
            )
            .scalars()
            .first()
        )
        assert row is not None
        assert row.user_id == user.id
        assert row.clinician_id == provider.id


async def test_get_by_pair_returns_existing_edge(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    provider = await _seed_provider(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        await repo.add_favorite(user_id=user.id, clinician_id=provider.id)
        await session.commit()

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        edge = await repo.get_by_pair(user_id=user.id, clinician_id=provider.id)
        assert edge is not None
        assert edge.user_id == user.id
        assert edge.clinician_id == provider.id


async def test_get_by_pair_returns_none_when_absent(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    provider = await _seed_provider(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        edge = await repo.get_by_pair(user_id=user.id, clinician_id=provider.id)
        assert edge is None


async def test_delete_favorite_removes_edge(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    provider = await _seed_provider(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        edge = await repo.add_favorite(user_id=user.id, clinician_id=provider.id)
        await session.commit()
        edge_id = edge.id

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        edge = await repo.get_by_pair(user_id=user.id, clinician_id=provider.id)
        await repo.delete_favorite(edge)
        await session.commit()

    async with db_test_session_manager() as session:
        row = (
            (
                await session.execute(
                    select(UserFavorite).filter(UserFavorite.id == edge_id)
                )
            )
            .scalars()
            .first()
        )
        assert row is None


async def test_list_favorited_clinicians_newest_first(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Ordering is by `UserFavorite.created_at DESC`. SQLite's
    server-default `CURRENT_TIMESTAMP` is second-precision, so two
    inserts in the same second tie on ordering. The test bypasses
    `add_favorite` (which doesn't accept `created_at`) and inserts
    `UserFavorite` rows directly with explicit timestamps to force a
    deterministic ordering without `asyncio.sleep`. The repo
    listing's `created_at DESC` is what's under test, not the writer."""
    user = await _seed_user(db_test_session_manager)
    first = await _seed_provider(db_test_session_manager, practice_name="First")
    second = await _seed_provider(db_test_session_manager, practice_name="Second")
    earlier = datetime.now(timezone.utc)
    later = earlier + timedelta(seconds=1)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                UserFavorite(user_id=user.id, clinician_id=first.id, created_at=earlier)
            )
            session.add(
                UserFavorite(user_id=user.id, clinician_id=second.id, created_at=later)
            )

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        providers = await repo.list_favorited_clinicians(user.id)
        names = [p.org.name for p in providers]
        assert names == ["Second", "First"]


async def test_list_favorited_clinicians_empty(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        providers = await repo.list_favorited_clinicians(user.id)
        assert list(providers) == []


async def test_is_favorited_truth_table(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    favorited = await _seed_provider(db_test_session_manager)
    not_favorited = await _seed_provider(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        await repo.add_favorite(user_id=user.id, clinician_id=favorited.id)
        await session.commit()

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        assert await repo.is_favorited(user_id=user.id, clinician_id=favorited.id)
        assert not await repo.is_favorited(
            user_id=user.id, clinician_id=not_favorited.id
        )
