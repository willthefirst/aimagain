"""Tests for `OrganizationRepository` — the bespoke `create` / `patch`
overrides that maintain the ``root_org_id`` denormalization invariant.

The invariant (see ``src/domain/models/organizations/README.md``):

* root org (`parent_org_id IS NULL`) → ``root_org_id = id``.
* non-root → ``root_org_id = parent.root_org_id``.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.models import Organization
from src.framework.http.exceptions import NotFoundError
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio


def _new_org(*, owner_id, parent_org_id=None, name="Acme", type_="clinic"):
    return Organization(
        name=name,
        type=type_,
        owner_id=owner_id,
        parent_org_id=parent_org_id,
    )


async def test_create_root_sets_root_to_self_id(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)

    async with db_test_session_manager() as session:
        async with session.begin():
            repo = OrganizationRepository(session)
            org = await repo.create(_new_org(owner_id=user.id, type_="health_system"))
            assert org.id is not None
            assert org.root_org_id == org.id
            assert org.parent_org_id is None


async def test_create_child_inherits_root_from_parent(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)

    async with db_test_session_manager() as session:
        async with session.begin():
            repo = OrganizationRepository(session)
            root = await repo.create(_new_org(owner_id=user.id, type_="health_system"))
            child = await repo.create(
                _new_org(owner_id=user.id, parent_org_id=root.id, type_="clinic")
            )
            grandchild = await repo.create(
                _new_org(
                    owner_id=user.id, parent_org_id=child.id, type_="group_practice"
                )
            )
            assert child.root_org_id == root.id
            assert grandchild.root_org_id == root.id


async def test_create_with_unknown_parent_raises_not_found(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)

    bogus_parent = uuid.uuid4()
    async with db_test_session_manager() as session:
        repo = OrganizationRepository(session)
        with pytest.raises(NotFoundError):
            await repo.create(_new_org(owner_id=user.id, parent_org_id=bogus_parent))


async def test_patch_reparent_recomputes_root(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)

    async with db_test_session_manager() as session:
        async with session.begin():
            repo = OrganizationRepository(session)
            root_a = await repo.create(
                _new_org(owner_id=user.id, type_="health_system")
            )
            root_b = await repo.create(
                _new_org(owner_id=user.id, type_="health_system")
            )
            child = await repo.create(
                _new_org(owner_id=user.id, parent_org_id=root_a.id, type_="clinic")
            )
            assert child.root_org_id == root_a.id

            # Reparent to root_b — root must follow.
            await repo.patch(child, parent_org_id=root_b.id)
            assert child.parent_org_id == root_b.id
            assert child.root_org_id == root_b.id


async def test_patch_promote_to_root_recomputes_root(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)

    async with db_test_session_manager() as session:
        async with session.begin():
            repo = OrganizationRepository(session)
            root = await repo.create(_new_org(owner_id=user.id, type_="health_system"))
            child = await repo.create(
                _new_org(owner_id=user.id, parent_org_id=root.id, type_="clinic")
            )

            # Promote child to its own root by clearing parent.
            await repo.patch(child, parent_org_id=None)
            assert child.parent_org_id is None
            assert child.root_org_id == child.id


async def test_patch_ordinary_field_leaves_root_unchanged(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)

    async with db_test_session_manager() as session:
        async with session.begin():
            repo = OrganizationRepository(session)
            org = await repo.create(_new_org(owner_id=user.id, type_="health_system"))
            original_root = org.root_org_id
            await repo.patch(org, name="Renamed Health")
            assert org.name == "Renamed Health"
            assert org.root_org_id == original_root
