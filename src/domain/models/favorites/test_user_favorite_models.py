"""DB-layer tests for `UserFavorite`.

Pins what the table owns: the `(user_id, clinician_id)` uniqueness pin
(re-favoriting raises `IntegrityError`), and the CASCADE behavior on
both FKs — deleting either the user or the clinician purges the edge.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import Clinician, User, UserFavorite
from tests.helpers import create_test_user, make_organization_row

pytestmark = pytest.mark.asyncio


async def _seed_user_and_clinician(
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> tuple[User, Clinician]:
    user = create_test_user()
    owner = create_test_user()
    org = make_organization_row(owner_id=owner.id)
    clinician = Clinician(
        owner_id=owner.id,
        org_id=org.id,
        in_person_sessions="yes",
        virtual_sessions="no",
        location_city="Springfield",
        location_state="IL",
        location_zip="62701",
    )
    clinician.org = org
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(owner)
            session.add(clinician)
    return user, clinician


async def test_create_user_favorite_persists(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, clinician = await _seed_user_and_clinician(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(UserFavorite(user_id=user.id, clinician_id=clinician.id))

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
        assert rows[0].clinician_id == clinician.id


async def test_duplicate_pair_violates_unique_constraint(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, clinician = await _seed_user_and_clinician(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(UserFavorite(user_id=user.id, clinician_id=clinician.id))

    with pytest.raises(IntegrityError):
        async with db_test_session_manager() as session:
            async with session.begin():
                session.add(UserFavorite(user_id=user.id, clinician_id=clinician.id))


async def test_delete_user_cascades_favorites(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, clinician = await _seed_user_and_clinician(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(UserFavorite(user_id=user.id, clinician_id=clinician.id))

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


async def test_delete_clinician_cascades_favorites(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, clinician = await _seed_user_and_clinician(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(UserFavorite(user_id=user.id, clinician_id=clinician.id))

    async with db_test_session_manager() as session:
        async with session.begin():
            loaded = await session.get(Clinician, clinician.id)
            await session.delete(loaded)

    async with db_test_session_manager() as session:
        rows = (
            (
                await session.execute(
                    select(UserFavorite).filter(
                        UserFavorite.clinician_id == clinician.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows == []
