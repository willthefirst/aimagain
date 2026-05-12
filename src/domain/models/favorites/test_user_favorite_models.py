"""DB-layer tests for `UserFavorite`.

Pins what the table owns: the `(user_id, provider_id)` uniqueness pin
(re-favoriting raises `IntegrityError`), and the CASCADE behavior on
both FKs — deleting either the user or the provider purges the edge.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import Provider, User, UserFavorite
from tests.helpers import create_test_user, make_provider

pytestmark = pytest.mark.asyncio


async def _seed_user_and_provider(
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> tuple[User, Provider]:
    user = create_test_user()
    owner = create_test_user()
    provider = make_provider(owner_id=owner.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(owner)
            session.add(provider)
    return user, provider


async def test_create_user_favorite_persists(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, provider = await _seed_user_and_provider(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(UserFavorite(user_id=user.id, provider_id=provider.id))

    async with db_test_session_manager() as session:
        rows = (
            (
                await session.execute(
                    select(UserFavorite).filter(UserFavorite.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].provider_id == provider.id


async def test_duplicate_pair_violates_unique_constraint(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, provider = await _seed_user_and_provider(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(UserFavorite(user_id=user.id, provider_id=provider.id))

    with pytest.raises(IntegrityError):
        async with db_test_session_manager() as session:
            async with session.begin():
                session.add(UserFavorite(user_id=user.id, provider_id=provider.id))


async def test_delete_user_cascades_favorites(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, provider = await _seed_user_and_provider(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(UserFavorite(user_id=user.id, provider_id=provider.id))

    async with db_test_session_manager() as session:
        async with session.begin():
            loaded = await session.get(User, user.id)
            await session.delete(loaded)

    async with db_test_session_manager() as session:
        rows = (
            (
                await session.execute(
                    select(UserFavorite).filter(UserFavorite.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert rows == []


async def test_delete_provider_cascades_favorites(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, provider = await _seed_user_and_provider(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(UserFavorite(user_id=user.id, provider_id=provider.id))

    async with db_test_session_manager() as session:
        async with session.begin():
            loaded = await session.get(Provider, provider.id)
            await session.delete(loaded)

    async with db_test_session_manager() as session:
        rows = (
            (
                await session.execute(
                    select(UserFavorite).filter(UserFavorite.provider_id == provider.id)
                )
            )
            .scalars()
            .all()
        )
        assert rows == []
