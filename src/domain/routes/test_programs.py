"""HTTP-level tests for `/programs`.

End-to-end CRUD: list / detail render, create / patch / delete work,
the ``payload_authz_path`` hook (#535) gates POST/PATCH on Org
ownership (403 for unowned, 404 for nonexistent, superuser bypass),
and ``form_extras_path`` (#534) scopes the create / edit form's
Org-picker to the user's owned Orgs.
"""

import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import Program, User
from src.framework.audit.repository import AuditRepository
from tests.helpers import (
    create_test_user,
    make_organization_row,
    promote_to_admin,
)

pytestmark = pytest.mark.asyncio


# --- Helpers -------------------------------------------------------------


def _program_payload(*, org_id: uuid.UUID, **overrides):
    base = {"org_id": str(org_id), "name": "RISE IOP"}
    return {**base, **overrides}


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


async def _seed_program_for(
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


async def _audit_rows_for(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    resource_id: uuid.UUID,
):
    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        return await repo.list_for_resource(
            resource_type="program", resource_id=resource_id
        )


# --- Create --------------------------------------------------------------


async def test_create_program_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    org_id = await _seed_org(db_test_session_manager, owner_id=logged_in_user.id)
    response = await authenticated_client.post(
        "/programs", data=_program_payload(org_id=org_id)
    )
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])
    assert response.headers["Location"] == f"/programs/{new_id}"
    assert response.headers["HX-Redirect"] == f"/programs/{new_id}/form"

    async with db_test_session_manager() as session:
        loaded = await session.get(Program, new_id)
        assert loaded is not None
        assert loaded.owner_id == logged_in_user.id
        assert loaded.org_id == org_id
        assert loaded.name == "RISE IOP"
        assert loaded.accepting_referrals is True

    rows = await _audit_rows_for(db_test_session_manager, resource_id=new_id)
    assert len(rows) == 1
    assert rows[0].action == "create_program"
    assert rows[0].actor_id == logged_in_user.id


async def test_create_program_with_blank_optional_form_fields_succeeds(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Regression: ``programs/form_new.html`` posts blank optional
    inputs as ``""`` — including ``description=``, ``start_date=``,
    ``end_date=``, ``state_preference=`` (left at placeholder). Prior
    to the model-level coercion on ``WirePayload``
    (:func:`_coerce_blank_strings_on_nullable_scalars`), `date | None`
    and `Literal[...] | None` 422'd before the `None` arm was even
    considered — same class of bug as #550 on `parent_org_id`. Pin the
    accepting behavior here so the next regression on `WirePayload`
    surfaces at this layer."""
    org_id = await _seed_org(db_test_session_manager, owner_id=logged_in_user.id)
    response = await authenticated_client.post(
        "/programs",
        data=_program_payload(
            org_id=org_id,
            description="",
            state_preference="",
            start_date="",
            end_date="",
        ),
    )
    assert response.status_code == 201, response.text
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        loaded = await session.get(Program, new_id)
        assert loaded is not None
        assert loaded.description is None
        assert loaded.state_preference is None
        assert loaded.start_date is None
        assert loaded.end_date is None


async def test_create_program_rejects_org_owned_by_another_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Conformance check for ``payload_authz_path``: a POST whose
    ``org_id`` points at another user's Org returns 403, not 201."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    other_org_id = await _seed_org(
        db_test_session_manager, owner_id=other.id, name="Other's Org"
    )

    response = await authenticated_client.post(
        "/programs", data=_program_payload(org_id=other_org_id)
    )
    assert response.status_code == 403


async def test_create_program_rejects_nonexistent_org(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """A POST with a bogus ``org_id`` returns 404 (no info leak about
    other users' Org ids; also avoids the 500 the FK would otherwise
    produce)."""
    bogus = uuid.uuid4()
    response = await authenticated_client.post(
        "/programs", data=_program_payload(org_id=bogus)
    )
    assert response.status_code == 404


async def test_create_program_superuser_can_attach_to_any_org(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Superuser bypass on the ``payload_authz_path`` hook."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    other_org_id = await _seed_org(
        db_test_session_manager, owner_id=other.id, name="Other's Org"
    )

    response = await authenticated_client.post(
        "/programs", data=_program_payload(org_id=other_org_id)
    )
    assert response.status_code == 201


# --- Reads ---------------------------------------------------------------


async def test_list_programs_renders(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    org_id = await _seed_org(db_test_session_manager, owner_id=logged_in_user.id)
    await _seed_program_for(
        db_test_session_manager,
        owner_id=logged_in_user.id,
        org_id=org_id,
        name="Listable Program",
    )
    response = await authenticated_client.get("/programs")
    assert response.status_code == 200
    assert "Listable Program" in response.text


async def test_detail_renders(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    org_id = await _seed_org(db_test_session_manager, owner_id=logged_in_user.id)
    program_id = await _seed_program_for(
        db_test_session_manager,
        owner_id=logged_in_user.id,
        org_id=org_id,
        name="Detail Program",
    )
    response = await authenticated_client.get(f"/programs/{program_id}")
    assert response.status_code == 200
    assert "Detail Program" in response.text


async def test_form_new_dropdown_lists_owned_orgs_only(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Conformance check for ``form_extras_path``: GET /programs/form
    renders an Org-picker scoped to the user's owned Orgs."""
    owned_id = await _seed_org(
        db_test_session_manager, owner_id=logged_in_user.id, name="Mine"
    )
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    other_org_id = await _seed_org(
        db_test_session_manager, owner_id=other.id, name="Other's"
    )

    response = await authenticated_client.get("/programs/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    options = tree.css('select[name="org_id"] option')
    values = {opt.attributes.get("value") for opt in options}
    assert str(owned_id) in values
    assert str(other_org_id) not in values


async def test_form_edit_pre_selects_attached_org(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    org_id = await _seed_org(
        db_test_session_manager, owner_id=logged_in_user.id, name="Mine"
    )
    program_id = await _seed_program_for(
        db_test_session_manager, owner_id=logged_in_user.id, org_id=org_id
    )
    response = await authenticated_client.get(f"/programs/{program_id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    selected = tree.css_first('select[name="org_id"] option[selected]')
    assert selected is not None
    assert selected.attributes.get("value") == str(org_id)


# --- Update --------------------------------------------------------------


async def test_patch_updates_name(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    org_id = await _seed_org(db_test_session_manager, owner_id=logged_in_user.id)
    program_id = await _seed_program_for(
        db_test_session_manager, owner_id=logged_in_user.id, org_id=org_id
    )
    response = await authenticated_client.patch(
        f"/programs/{program_id}", data={"name": "Renamed Program"}
    )
    assert response.status_code in (200, 204)

    async with db_test_session_manager() as session:
        loaded = await session.get(Program, program_id)
        assert loaded is not None
        assert loaded.name == "Renamed Program"


async def test_patch_rejects_unowned_org_id(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The ``payload_authz`` hook runs on PATCH too — repointing
    ``org_id`` at another user's Org is 403."""
    org_id = await _seed_org(db_test_session_manager, owner_id=logged_in_user.id)
    program_id = await _seed_program_for(
        db_test_session_manager, owner_id=logged_in_user.id, org_id=org_id
    )
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    other_org_id = await _seed_org(
        db_test_session_manager, owner_id=other.id, name="Other's"
    )

    response = await authenticated_client.patch(
        f"/programs/{program_id}", data={"org_id": str(other_org_id)}
    )
    assert response.status_code == 403


async def test_patch_rejects_nonexistent_org_id(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    org_id = await _seed_org(db_test_session_manager, owner_id=logged_in_user.id)
    program_id = await _seed_program_for(
        db_test_session_manager, owner_id=logged_in_user.id, org_id=org_id
    )
    bogus = uuid.uuid4()
    response = await authenticated_client.patch(
        f"/programs/{program_id}", data={"org_id": str(bogus)}
    )
    assert response.status_code == 404


# --- Delete --------------------------------------------------------------


async def test_delete_program(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    org_id = await _seed_org(db_test_session_manager, owner_id=logged_in_user.id)
    program_id = await _seed_program_for(
        db_test_session_manager, owner_id=logged_in_user.id, org_id=org_id
    )
    response = await authenticated_client.delete(f"/programs/{program_id}")
    assert response.status_code in (200, 204)

    async with db_test_session_manager() as session:
        result = await session.execute(select(Program).filter(Program.id == program_id))
        assert result.scalars().first() is None

    rows = await _audit_rows_for(db_test_session_manager, resource_id=program_id)
    assert any(r.action == "delete_program" for r in rows)
