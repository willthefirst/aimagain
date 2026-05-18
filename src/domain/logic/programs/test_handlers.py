"""Tests for `Program` per-spec hook callables.

Two hooks, both load-bearing:

* ``program_form_extras`` — owners see their owned Orgs; superusers
  see every Org; the edit path appends the currently-attached Org
  even when the user no longer owns it.
* ``_assert_program_payload_org_ownership`` — 403 for unowned, 404
  for nonexistent, no-op on PATCH with ``org_id=None``, bypass for
  superusers.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.programs.handlers import (
    _assert_program_payload_org_ownership,
    program_form_extras,
)
from src.domain.logic.programs.repository import ProgramRepository
from src.domain.logic.programs.schema import ProgramCreate, ProgramUpdate
from src.domain.models import Program, User
from src.framework.http.exceptions import ForbiddenError, NotFoundError
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
    name: str = "Acme Health",
) -> uuid.UUID:
    org = make_organization_row(owner_id=owner_id, name=name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(org)
    return org.id


async def _seed_program(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    owner_id: uuid.UUID,
    org_id: uuid.UUID,
    name: str = "RISE IOP",
) -> uuid.UUID:
    program = Program(owner_id=owner_id, org_id=org_id, name=name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(program)
        await session.refresh(program)
        return program.id


# --- program_form_extras -------------------------------------------------


async def test_program_form_extras_returns_owned_orgs(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Owner sees only the Orgs they own (create path)."""
    owner = await _seed_user(db_test_session_manager)
    stranger = await _seed_user(db_test_session_manager)
    owned_id = await _seed_org(db_test_session_manager, owner_id=owner.id, name="Mine")
    await _seed_org(db_test_session_manager, owner_id=stranger.id, name="Other")

    async with db_test_session_manager() as session:
        org_repo = OrganizationRepository(session)
        result = await program_form_extras(
            target=None, requesting_user=owner, organization_repo=org_repo
        )
        assert [o.id for o in result["organizations"]] == [owned_id]


async def test_program_form_extras_superuser_sees_all_orgs(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    admin = await _seed_user(db_test_session_manager, is_superuser=True)
    other = await _seed_user(db_test_session_manager)
    await _seed_org(db_test_session_manager, owner_id=admin.id, name="Admin Org")
    await _seed_org(db_test_session_manager, owner_id=other.id, name="Other Org")

    async with db_test_session_manager() as session:
        org_repo = OrganizationRepository(session)
        result = await program_form_extras(
            target=None, requesting_user=admin, organization_repo=org_repo
        )
        names = {o.name for o in result["organizations"]}
        assert "Admin Org" in names
        assert "Other Org" in names


async def test_program_form_extras_edit_path_includes_attached_org_even_if_unowned(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """If a Program is attached to an Org the requesting user doesn't
    own (e.g. an admin editing someone else's, or post-ownership-
    transfer), the dropdown still includes the attached Org so the
    form doesn't silently drop the FK on submit."""
    editor = await _seed_user(db_test_session_manager)
    stranger = await _seed_user(db_test_session_manager)
    owned_id = await _seed_org(db_test_session_manager, owner_id=editor.id, name="Mine")
    unowned_id = await _seed_org(
        db_test_session_manager, owner_id=stranger.id, name="Theirs"
    )
    program_id = await _seed_program(
        db_test_session_manager, owner_id=editor.id, org_id=unowned_id
    )

    async with db_test_session_manager() as session:
        program_repo = ProgramRepository(session)
        program = await program_repo.get_by_model_id(Program, program_id)
        org_repo = OrganizationRepository(session)
        result = await program_form_extras(
            target=program, requesting_user=editor, organization_repo=org_repo
        )
        ids = {o.id for o in result["organizations"]}
        assert owned_id in ids
        assert unowned_id in ids


async def test_program_form_extras_edit_path_omits_duplicate_when_attached_is_owned(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """When the attached Org *is* in the user's owned set, it appears
    once — the edit-path special case doesn't duplicate it."""
    owner = await _seed_user(db_test_session_manager)
    owned_id = await _seed_org(db_test_session_manager, owner_id=owner.id, name="Mine")
    program_id = await _seed_program(
        db_test_session_manager, owner_id=owner.id, org_id=owned_id
    )

    async with db_test_session_manager() as session:
        program_repo = ProgramRepository(session)
        program = await program_repo.get_by_model_id(Program, program_id)
        org_repo = OrganizationRepository(session)
        result = await program_form_extras(
            target=program, requesting_user=owner, organization_repo=org_repo
        )
        ids = [o.id for o in result["organizations"]]
        assert ids.count(owned_id) == 1


# --- _assert_program_payload_org_ownership ------------------------------


async def test_payload_authz_allows_owner_attaching_to_owned_org(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner = await _seed_user(db_test_session_manager)
    owned_id = await _seed_org(db_test_session_manager, owner_id=owner.id)
    payload = ProgramCreate(org_id=owned_id, name="RISE IOP")

    async with db_test_session_manager() as session:
        org_repo = OrganizationRepository(session)
        # Does not raise.
        await _assert_program_payload_org_ownership(
            payload=payload, requesting_user=owner, organization_repo=org_repo
        )


async def test_payload_authz_rejects_unowned_org(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    stranger = await _seed_user(db_test_session_manager)
    unowned_id = await _seed_org(db_test_session_manager, owner_id=stranger.id)
    payload = ProgramCreate(org_id=unowned_id, name="RISE IOP")

    async with db_test_session_manager() as session:
        org_repo = OrganizationRepository(session)
        with pytest.raises(ForbiddenError):
            await _assert_program_payload_org_ownership(
                payload=payload, requesting_user=user, organization_repo=org_repo
            )


async def test_payload_authz_rejects_nonexistent_org(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    bogus = uuid.uuid4()
    payload = ProgramCreate(org_id=bogus, name="RISE IOP")

    async with db_test_session_manager() as session:
        org_repo = OrganizationRepository(session)
        with pytest.raises(NotFoundError):
            await _assert_program_payload_org_ownership(
                payload=payload, requesting_user=user, organization_repo=org_repo
            )


async def test_payload_authz_superuser_bypasses(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    admin = await _seed_user(db_test_session_manager, is_superuser=True)
    other = await _seed_user(db_test_session_manager)
    other_org_id = await _seed_org(db_test_session_manager, owner_id=other.id)
    payload = ProgramCreate(org_id=other_org_id, name="RISE IOP")

    async with db_test_session_manager() as session:
        org_repo = OrganizationRepository(session)
        # Does not raise — superuser bypass.
        await _assert_program_payload_org_ownership(
            payload=payload, requesting_user=admin, organization_repo=org_repo
        )


async def test_payload_authz_noop_when_org_id_absent(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """PATCH payloads that don't set ``org_id`` skip the check entirely
    — only flow through ownership when the payload actually proposes a
    new Org. (Mirrors the Provider analog.)"""
    user = await _seed_user(db_test_session_manager)
    payload = ProgramUpdate(name="Renamed")
    assert payload.org_id is None

    async with db_test_session_manager() as session:
        org_repo = OrganizationRepository(session)
        # Does not raise even though no Org has been created.
        await _assert_program_payload_org_ownership(
            payload=payload, requesting_user=user, organization_repo=org_repo
        )
