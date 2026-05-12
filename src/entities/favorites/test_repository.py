"""Tests for `UserFavoriteRepository`.

Exercises CRUD on the M:N edge plus the listing join. Idempotency is
*not* enforced here — the repo lets the unique constraint speak; the
logic layer is responsible for `get_by_pair` before `add_favorite`. This
test file pins the listing's newest-first ordering and the `is_favorited`
truth table.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.entities.favorites.repository import UserFavoriteRepository
from src.models import User, UserFavorite
from tests.helpers import create_test_user, make_provider

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
    provider = make_provider(owner_id=owner.id, practice_name=practice_name)
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
        edge = await repo.add_favorite(user_id=user.id, provider_id=provider.id)
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
        assert row.provider_id == provider.id


async def test_get_by_pair_returns_existing_edge(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    provider = await _seed_provider(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        await repo.add_favorite(user_id=user.id, provider_id=provider.id)
        await session.commit()

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        edge = await repo.get_by_pair(user_id=user.id, provider_id=provider.id)
        assert edge is not None
        assert edge.user_id == user.id
        assert edge.provider_id == provider.id


async def test_get_by_pair_returns_none_when_absent(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    provider = await _seed_provider(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        edge = await repo.get_by_pair(user_id=user.id, provider_id=provider.id)
        assert edge is None


async def test_delete_favorite_removes_edge(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    provider = await _seed_provider(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        edge = await repo.add_favorite(user_id=user.id, provider_id=provider.id)
        await session.commit()
        edge_id = edge.id

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        edge = await repo.get_by_pair(user_id=user.id, provider_id=provider.id)
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


async def test_list_favorited_providers_newest_first(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Ordering is by `UserFavorite.created_at DESC`. We add two edges
    with a short sleep between to force a different timestamp on SQLite."""
    user = await _seed_user(db_test_session_manager)
    first = await _seed_provider(db_test_session_manager, practice_name="First")
    second = await _seed_provider(db_test_session_manager, practice_name="Second")

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        await repo.add_favorite(user_id=user.id, provider_id=first.id)
        await session.commit()

    await asyncio.sleep(1.1)

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        await repo.add_favorite(user_id=user.id, provider_id=second.id)
        await session.commit()

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        providers = await repo.list_favorited_providers(user.id)
        names = [p.practice_name for p in providers]
        assert names == ["Second", "First"]


async def test_list_favorited_providers_empty(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        providers = await repo.list_favorited_providers(user.id)
        assert list(providers) == []


async def test_is_favorited_truth_table(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    favorited = await _seed_provider(db_test_session_manager)
    not_favorited = await _seed_provider(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        await repo.add_favorite(user_id=user.id, provider_id=favorited.id)
        await session.commit()

    async with db_test_session_manager() as session:
        repo = UserFavoriteRepository(session)
        assert await repo.is_favorited(user_id=user.id, provider_id=favorited.id)
        assert not await repo.is_favorited(
            user_id=user.id, provider_id=not_favorited.id
        )
