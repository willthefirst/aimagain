"""Tests for `Organization` per-spec hook callables.

Pins :func:`organization_form_extras` — the parent-Org picker hook
(issue #581):

* Non-superuser sees only Orgs they own.
* Superuser sees every Org.
* Edit path excludes the row being edited (self-loop prevention).
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.organizations.handlers import organization_form_extras
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.models import Organization, User
from tests.helpers import create_test_user, make_organization_row

pytestmark = pytest.mark.asyncio


# --- Seeding helpers -----------------------------------------------------


async def _seed_user(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    is_superuser: bool = False,
) -> User:
    user = create_test_user(username=f"u-{uuid.uuid4()}", is_superuser=is_superuser)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
    return user


async def _seed_org(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    owner_id: uuid.UUID,
    name: str,
) -> uuid.UUID:
    org = make_organization_row(owner_id=owner_id, name=name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(org)
    return org.id


# --- organization_form_extras --------------------------------------------


async def test_form_extras_owner_sees_only_owned_orgs(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Create path (target=None): non-superuser sees only Orgs they own."""
    owner = await _seed_user(db_test_session_manager)
    stranger = await _seed_user(db_test_session_manager)
    owned_id = await _seed_org(db_test_session_manager, owner_id=owner.id, name="Mine")
    await _seed_org(db_test_session_manager, owner_id=stranger.id, name="Other")

    async with db_test_session_manager() as session:
        org_repo = OrganizationRepository(session)
        result = await organization_form_extras(
            target=None, requesting_user=owner, organization_repo=org_repo
        )
        ids = [o.id for o in result["parent_org_options"]]
        assert ids == [owned_id]


async def test_form_extras_superuser_sees_all_orgs(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Superuser sees every Org regardless of owner."""
    admin = await _seed_user(db_test_session_manager, is_superuser=True)
    other = await _seed_user(db_test_session_manager)
    await _seed_org(db_test_session_manager, owner_id=admin.id, name="Admin Org")
    await _seed_org(db_test_session_manager, owner_id=other.id, name="Other Org")

    async with db_test_session_manager() as session:
        org_repo = OrganizationRepository(session)
        result = await organization_form_extras(
            target=None, requesting_user=admin, organization_repo=org_repo
        )
        names = {o.name for o in result["parent_org_options"]}
        assert "Admin Org" in names
        assert "Other Org" in names


async def test_form_extras_edit_path_excludes_self(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Edit path: the row being edited is excluded from picker options
    so the form can't pin a self-loop on submit (an Org as its own
    parent)."""
    owner = await _seed_user(db_test_session_manager)
    self_id = await _seed_org(db_test_session_manager, owner_id=owner.id, name="Self")
    sibling_id = await _seed_org(
        db_test_session_manager, owner_id=owner.id, name="Sibling"
    )

    async with db_test_session_manager() as session:
        org_repo = OrganizationRepository(session)
        target = await org_repo.get_by_model_id(Organization, self_id)
        result = await organization_form_extras(
            target=target, requesting_user=owner, organization_repo=org_repo
        )
        ids = {o.id for o in result["parent_org_options"]}
        assert self_id not in ids
        assert sibling_id in ids
