"""Tests for the `Program` model.

Exercises the invariants the DB layer owns: the FK to ``organizations``
(RESTRICT — deleting an Org with Programs fails loudly), the FK to
``users`` (CASCADE — deleting an owning User deletes their Programs),
and the CHECK on ``state_preference`` against :data:`US_STATES`.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import Organization, Program, User
from tests.helpers import create_test_user, make_organization_row

pytestmark = pytest.mark.asyncio


def _make_program(*, owner_id: uuid.UUID, org_id: uuid.UUID, **overrides) -> Program:
    defaults = dict(name="RISE IOP")
    return Program(owner_id=owner_id, org_id=org_id, **{**defaults, **overrides})


async def test_create_program_persists(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    org = make_organization_row(owner_id=user.id, name="CHC")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(org)
            session.add(_make_program(owner_id=user.id, org_id=org.id))

    async with db_test_session_manager() as session:
        program = (
            (await session.execute(select(Program).filter(Program.org_id == org.id)))
            .scalars()
            .first()
        )
        assert program is not None
        assert program.name == "RISE IOP"
        # Defaults populated.
        assert program.accepting_referrals is True
        assert program.state_preference is None
        assert program.description is None


async def test_program_state_preference_check_rejects_unknown(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The ``ck_programs_state_preference`` CHECK rejects any value not
    in :data:`US_STATES`."""
    user = create_test_user()
    org = make_organization_row(owner_id=user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(org)

    async with db_test_session_manager() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    _make_program(
                        owner_id=user.id, org_id=org.id, state_preference="ZZ"
                    )
                )


async def test_program_state_preference_accepts_us_state(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    org = make_organization_row(owner_id=user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(org)
            session.add(
                _make_program(owner_id=user.id, org_id=org.id, state_preference="CA")
            )

    async with db_test_session_manager() as session:
        program = (await session.execute(select(Program))).scalars().first()
        assert program is not None
        assert program.state_preference == "CA"


async def test_delete_owner_cascades_to_program(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """``programs.owner_id`` FK cascades on delete — deleting the owning
    User removes their Programs."""
    user = create_test_user()
    org = make_organization_row(owner_id=user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(org)
            session.add(_make_program(owner_id=user.id, org_id=org.id))

    async with db_test_session_manager() as session:
        async with session.begin():
            loaded = await session.get(User, user.id)
            await session.delete(loaded)

    async with db_test_session_manager() as session:
        remaining = (await session.execute(select(Program))).scalars().all()
        assert remaining == []


async def test_delete_org_with_programs_is_restricted(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """``programs.org_id`` FK is RESTRICT — deleting an Org with
    Programs fails loudly rather than silently orphaning them."""
    user = create_test_user()
    org = make_organization_row(owner_id=user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(org)
            session.add(_make_program(owner_id=user.id, org_id=org.id))

    async with db_test_session_manager() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                loaded = await session.get(Organization, org.id)
                await session.delete(loaded)


async def test_program_org_name_property(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """``Program.org_name`` returns ``program.organization.name``; used
    by ``ProgramRead`` via ``from_attributes``."""
    user = create_test_user()
    org = make_organization_row(owner_id=user.id, name="Mind Springs")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(org)
            session.add(_make_program(owner_id=user.id, org_id=org.id))

    async with db_test_session_manager() as session:
        program = (
            (await session.execute(select(Program).filter(Program.org_id == org.id)))
            .scalars()
            .first()
        )
        assert program is not None
        assert program.org_name == "Mind Springs"
