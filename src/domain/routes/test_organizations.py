"""HTTP-level tests for `/organizations`.

End-to-end CRUD: create returns 201 with the redirect headers the
framework's `handle_create` injects, list and detail render, patch
updates fields, delete removes the row and writes an audit row.
"""

import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import Organization, User
from src.framework.audit.repository import AuditRepository
from tests.helpers import create_test_user, make_organization_row

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
    # Regression for #594 — the name appears in the header `<strong>`
    # only; the facts `<dl>` must not include a `<dt>Name</dt>` row
    # that duplicates the same string.
    assert "<dt>Name</dt>" not in detail_resp.text


async def test_detail_root_org_omits_parent_organization_row(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """Issue #595 — root organizations rendered `Parent organization: —
    (root)`, a mixed empty-state convention. Root orgs now omit the
    parent row entirely (matches the optional-field grammar used by
    posts/providers/programs detail templates)."""
    create_resp = await authenticated_client.post(
        "/organizations", data=_org_payload(name="Root-Org")
    )
    new_id = uuid.UUID(create_resp.json()["id"])
    detail_resp = await authenticated_client.get(f"/organizations/{new_id}")
    assert detail_resp.status_code == 200
    # The row is dropped — neither the placeholder text nor the dt label
    # appears for a root org.
    assert "Parent organization" not in detail_resp.text
    assert "(root)" not in detail_resp.text


async def test_detail_child_org_renders_parent_link(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """Counterpart to the root-omits test: when the org has a parent,
    the parent row renders with the parent's name as the link text."""
    parent_resp = await authenticated_client.post(
        "/organizations", data=_org_payload(name="Parent-Org")
    )
    parent_id = uuid.UUID(parent_resp.json()["id"])

    child_resp = await authenticated_client.post(
        "/organizations",
        data=_org_payload(
            name="Child-Org", type="clinic", parent_org_id=str(parent_id)
        ),
    )
    child_id = uuid.UUID(child_resp.json()["id"])

    detail_resp = await authenticated_client.get(f"/organizations/{child_id}")
    assert detail_resp.status_code == 200
    assert "Parent organization" in detail_resp.text
    # Parent name resolved as the link text (not the raw UUID).
    assert "Parent-Org" in detail_resp.text
    assert f"/organizations/{parent_id}" in detail_resp.text


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


# --- Parent-Org picker (issue #581) --------------------------------------


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


async def test_form_new_renders_parent_org_select_with_root_option(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Pins the new picker structure from issue #581: a ``<select
    name="parent_org_id">`` with a "(no parent)" default option plus
    one ``<option>`` per Org visible to the requesting user.
    """
    mine_a = await _seed_org(
        db_test_session_manager, owner_id=logged_in_user.id, name="Mine A"
    )
    mine_b = await _seed_org(
        db_test_session_manager, owner_id=logged_in_user.id, name="Mine B"
    )

    response = await authenticated_client.get("/organizations/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    select = tree.css_first('select[name="parent_org_id"]')
    assert select is not None, "parent-org picker should be a <select>"
    options = select.css("option")
    # Blank-option + one option per visible Org. selectolax surfaces
    # `value=""` as ``None`` in the attribute dict, so we test the
    # blank option by position + the absence of a value.
    assert len(options) == 3
    assert options[0].attributes.get("value") is None
    assert "selected" in options[0].attributes
    assert "no parent" in options[0].text().lower()
    values = {opt.attributes.get("value") for opt in options}
    # `None` is the blank option's value (empty-string attribute).
    assert values == {None, str(mine_a), str(mine_b)}
    # Free-text input from the prior UI is gone.
    assert tree.css_first('input[name="parent_org_id"]') is None


async def test_form_new_scopes_to_owned_orgs(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Non-superusers see only Orgs they own in the picker — same scope
    as the Program/Provider form pickers (see ``_orgs_visible_to``)."""
    mine = await _seed_org(
        db_test_session_manager, owner_id=logged_in_user.id, name="Mine"
    )
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    other_org = await _seed_org(
        db_test_session_manager, owner_id=other.id, name="Other's"
    )

    response = await authenticated_client.get("/organizations/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    values = {
        opt.attributes.get("value")
        for opt in tree.css('select[name="parent_org_id"] option')
    }
    assert str(mine) in values
    assert str(other_org) not in values


async def test_form_edit_excludes_self_from_picker(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """On edit, the org being edited is excluded from the picker
    options so the user can't pin a self-loop (org as its own parent).
    """
    self_id = await _seed_org(
        db_test_session_manager, owner_id=logged_in_user.id, name="Self"
    )
    sibling_id = await _seed_org(
        db_test_session_manager, owner_id=logged_in_user.id, name="Sibling"
    )

    response = await authenticated_client.get(f"/organizations/{self_id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    values = {
        opt.attributes.get("value")
        for opt in tree.css('select[name="parent_org_id"] option')
    }
    assert str(self_id) not in values
    assert str(sibling_id) in values
    # The "(root — no parent)" option remains as an explicit detach.
    # selectolax surfaces `value=""` as `None` in the attribute dict.
    assert None in values


async def test_form_edit_preselects_current_parent(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Edit form pre-selects the row's current ``parent_org_id`` in the
    picker; if the row is a root, the "(root — no parent)" option is
    selected instead.
    """
    parent_resp = await authenticated_client.post(
        "/organizations", data=_org_payload(name="Parent")
    )
    parent_id = uuid.UUID(parent_resp.json()["id"])
    child_resp = await authenticated_client.post(
        "/organizations",
        data=_org_payload(name="Child", type="clinic", parent_org_id=str(parent_id)),
    )
    child_id = uuid.UUID(child_resp.json()["id"])

    response = await authenticated_client.get(f"/organizations/{child_id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    selected = tree.css_first('select[name="parent_org_id"] option[selected]')
    assert selected is not None
    assert selected.attributes.get("value") == str(parent_id)


async def test_form_edit_preselects_root_for_top_level_org(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A root org (no parent) edits with the "(no parent)" option
    pre-selected."""
    create_resp = await authenticated_client.post(
        "/organizations", data=_org_payload(name="Top-Level")
    )
    org_id = uuid.UUID(create_resp.json()["id"])

    response = await authenticated_client.get(f"/organizations/{org_id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    selected = tree.css_first('select[name="parent_org_id"] option[selected]')
    assert selected is not None
    # `value=""` is rendered as the blank option; selectolax surfaces an
    # empty-string attribute as ``None``.
    assert selected.attributes.get("value") is None
    assert "no parent" in selected.text().lower()


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
