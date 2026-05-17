"""Direct DB-layer tests for the `Organization` model.

Exercises invariants the model + migration own — `type` CHECK against
`ORGANIZATION_TYPES`, hierarchy FKs, cascade on owner-user delete.
The `parent_org_id ↔ root_org_id` denormalization invariant is a
repository-level concern (see `domain/logic/organizations/test_repository.py`),
not a DB constraint — there is no CHECK enforcing it.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import Organization, User
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio


def _make_org(user: User, **overrides) -> Organization:
    org_id = overrides.pop("id", uuid.uuid4())
    defaults = dict(
        id=org_id,
        name="Acme Health System",
        type="health_system",
        owner_id=user.id,
        parent_org_id=None,
        root_org_id=org_id,
    )
    return Organization(**{**defaults, **overrides})


async def test_create_root_org_persists(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    org = _make_org(user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(org)

    async with db_test_session_manager() as session:
        loaded = (
            (
                await session.execute(
                    select(Organization).filter(Organization.id == org.id)
                )
            )
            .scalars()
            .first()
        )
        assert loaded is not None
        assert loaded.name == "Acme Health System"
        assert loaded.type == "health_system"
        assert loaded.parent_org_id is None
        assert loaded.root_org_id == org.id


async def test_type_check_rejects_unknown_value(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)

    bogus = _make_org(user, type="not_a_real_org_type")
    async with db_test_session_manager() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(bogus)


async def test_cascade_on_owner_delete_removes_org(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    org = _make_org(user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(org)

    async with db_test_session_manager() as session:
        async with session.begin():
            persisted_user = await session.get(User, user.id)
            await session.delete(persisted_user)

    async with db_test_session_manager() as session:
        loaded = (
            (
                await session.execute(
                    select(Organization).filter(Organization.id == org.id)
                )
            )
            .scalars()
            .first()
        )
        assert loaded is None


async def test_child_org_self_references_parent(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    parent = _make_org(user)
    child_id = uuid.uuid4()
    child = _make_org(
        user,
        id=child_id,
        name="Acme Downtown",
        type="clinic",
        parent_org_id=parent.id,
        root_org_id=parent.root_org_id,
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(parent)
            session.add(child)

    async with db_test_session_manager() as session:
        loaded = (
            (
                await session.execute(
                    select(Organization).filter(Organization.id == child_id)
                )
            )
            .scalars()
            .first()
        )
        assert loaded is not None
        assert loaded.parent_org_id == parent.id
        assert loaded.root_org_id == parent.root_org_id == parent.id
