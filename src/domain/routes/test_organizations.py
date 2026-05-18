"""HTTP-level tests for `/organizations`.

End-to-end CRUD: create returns 201 with the redirect headers the
framework's `handle_create` injects, list and detail render, patch
updates fields, delete removes the row and writes an audit row.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import Organization, User
from src.framework.audit.repository import AuditRepository

pytestmark = pytest.mark.asyncio


def _org_payload(**overrides):
    base = {"name": "Acme Health", "type": "health_system"}
    return {**base, **overrides}


async def _audit_rows_for(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    resource_id: uuid.UUID,
):
    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        return await repo.list_for_resource(
            resource_type="organization", resource_id=resource_id
        )


async def test_create_organization_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    response = await authenticated_client.post("/organizations", data=_org_payload())
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])
    assert response.headers["Location"] == f"/organizations/{new_id}"
    assert response.headers["HX-Redirect"] == f"/organizations/{new_id}/form"

    async with db_test_session_manager() as session:
        loaded = (
            (
                await session.execute(
                    select(Organization).filter(Organization.id == new_id)
                )
            )
            .scalars()
            .first()
        )
        assert loaded is not None
        assert loaded.owner_id == logged_in_user.id
        assert loaded.name == "Acme Health"
        # Root invariant — created with no parent, root points at self.
        assert loaded.parent_org_id is None
        assert loaded.root_org_id == new_id

    rows = await _audit_rows_for(db_test_session_manager, resource_id=new_id)
    assert len(rows) == 1
    assert rows[0].action == "create_organization"


async def test_create_organization_with_parent_inherits_root(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    parent_resp = await authenticated_client.post("/organizations", data=_org_payload())
    assert parent_resp.status_code == 201
    parent_id = uuid.UUID(parent_resp.json()["id"])

    child_resp = await authenticated_client.post(
        "/organizations",
        data=_org_payload(
            name="Downtown Clinic", type="clinic", parent_org_id=str(parent_id)
        ),
    )
    assert child_resp.status_code == 201
    child_id = uuid.UUID(child_resp.json()["id"])

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
        assert loaded.parent_org_id == parent_id
        assert loaded.root_org_id == parent_id


async def test_list_organizations_renders(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    create_resp = await authenticated_client.post(
        "/organizations", data=_org_payload(name="Listable Org")
    )
    assert create_resp.status_code == 201

    response = await authenticated_client.get("/organizations")
    assert response.status_code == 200
    assert "Listable Org" in response.text


async def test_detail_renders(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    create_resp = await authenticated_client.post(
        "/organizations", data=_org_payload(name="Detail-Org")
    )
    new_id = uuid.UUID(create_resp.json()["id"])
    detail_resp = await authenticated_client.get(f"/organizations/{new_id}")
    assert detail_resp.status_code == 200
    assert "Detail-Org" in detail_resp.text


async def test_patch_updates_name(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    create_resp = await authenticated_client.post("/organizations", data=_org_payload())
    new_id = uuid.UUID(create_resp.json()["id"])

    patch_resp = await authenticated_client.patch(
        f"/organizations/{new_id}", data={"name": "Renamed Org"}
    )
    assert patch_resp.status_code in (200, 204)

    async with db_test_session_manager() as session:
        loaded = await session.get(Organization, new_id)
        assert loaded is not None
        assert loaded.name == "Renamed Org"


async def test_create_organization_with_blank_parent_org_id_coerces_to_none(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Regression: HTML `form_new.html` posts ``parent_org_id=""`` when
    the optional input is left blank. Prior to `OptionalUuid` this 422'd
    on the wire — see ``OrganizationCreate.parent_org_id`` and
    ``framework.schema_validators.OptionalUuid``."""
    response = await authenticated_client.post(
        "/organizations",
        data=_org_payload(parent_org_id=""),
    )
    assert response.status_code == 201, response.text
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        loaded = await session.get(Organization, new_id)
        assert loaded is not None
        assert loaded.parent_org_id is None


async def test_get_organizations_form_resolves(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """Pins the create-form URL the templates link to.

    The grammar mandates ``GET /<collection>/form`` (not ``/new``). A
    prior set of provider/program templates linked to ``/organizations/new``,
    which silently matched ``GET /organizations/{organization_id}`` and
    returned a UUID-parse 422 in prod. Keep this test alongside the
    `/new` should-not-resolve assertion in `test_routes_meta` once that
    audit lands."""
    response = await authenticated_client.get("/organizations/form")
    assert response.status_code == 200


async def test_delete_removes_org(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    create_resp = await authenticated_client.post("/organizations", data=_org_payload())
    new_id = uuid.UUID(create_resp.json()["id"])

    del_resp = await authenticated_client.delete(f"/organizations/{new_id}")
    assert del_resp.status_code in (200, 204)

    async with db_test_session_manager() as session:
        loaded = await session.get(Organization, new_id)
        assert loaded is None
