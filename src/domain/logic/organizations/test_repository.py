"""Tests for `OrganizationRepository`.

`Organization` is a flat directory entity (no parent/root hierarchy) —
the repository inherits its create/patch behavior from
`BaseRepository` and adds only `list_for_user` for the owner-scoped
picker. Test coverage at this layer is thin; broader CRUD lives in
``src/domain/routes/test_organizations.py``.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.models import Organization
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio


def _new_org(*, owner_id, name="Acme"):
    return Organization(name=name, owner_id=owner_id)


async def test_create_assigns_id(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)

    async with db_test_session_manager() as session:
        async with session.begin():
            repo = OrganizationRepository(session)
            org = await repo.create(_new_org(owner_id=user.id))
            assert org.id is not None
            assert isinstance(org.id, uuid.UUID)


async def test_list_for_user_returns_owned_orgs(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)

    async with db_test_session_manager() as session:
        async with session.begin():
            repo = OrganizationRepository(session)
            await repo.create(_new_org(owner_id=user.id, name="One"))
            await repo.create(_new_org(owner_id=user.id, name="Two"))

    async with db_test_session_manager() as session:
        repo = OrganizationRepository(session)
        rows = await repo.list_for_user(user.id)
        assert {r.name for r in rows} == {"One", "Two"}
