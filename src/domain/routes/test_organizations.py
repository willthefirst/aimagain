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

from src.domain.models import Organization, OrgRepresentation, User
from src.framework.audit.repository import AuditRepository
from tests.helpers import create_test_user, make_clinician, make_organization_row

pytestmark = pytest.mark.asyncio


def _org_payload(**overrides):
    base = {"name": "Acme Health", "npi": "1234567890"}
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
    # Post-create now redirects to the homepage — the NPPES gate runs
    # before this point, so a successful response means the org is
    # already verified. See `ORGANIZATION_ENTITY.create_redirect` in
    # `src/domain/specs/organization.py`.
    assert response.headers["HX-Redirect"] == "/"

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

        # Self-registering an org grants the creator an immediately-verified
        # owner OrgRepresentation (#1166) — previously only the onboarding
        # hub did this; the canonical create now matches.
        owner_rep = (
            (
                await session.execute(
                    select(OrgRepresentation).filter(
                        OrgRepresentation.user_id == logged_in_user.id,
                        OrgRepresentation.org_id == new_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        assert owner_rep is not None
        assert owner_rep.role == "owner"
        assert owner_rep.authority_method == "admin_review"
        assert owner_rep.authority_status == "verified"

    rows = await _audit_rows_for(db_test_session_manager, resource_id=new_id)
    assert len(rows) == 1
    assert rows[0].action == "create_organization"


async def test_create_organization_form_error_render_is_wired(
    authenticated_client: AsyncClient,
):
    """Integration smoke for `ORGANIZATION_ENTITY.form_error_render`.

    HX-Request POST with an empty `name` trips the schema's
    min-length constraint → 422 + HTML fragment with the inline
    error landed on the `name` input via macro auto-resolution.

    Structural contracts (HX-Request gating, fragment-only response,
    422 status from PR #5) live in `test_post_families.py` /
    `test_create.py` — duplicating them here would be alphabet
    instead of grammar. This smoke just asserts the wiring is on
    end-to-end for this entity (the spec opt-in, the form's
    `with context` imports, the fragment file's existence).
    """
    response = await authenticated_client.post(
        "/organizations",
        data={"name": "", "npi": "1234567890"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    # `aria-invalid="true"` on the name input proves the macro layer
    # picked up `form_errors["name"]` from the rerender context.
    assert 'name="name"' in body
    name_at = body.index('name="name"')
    name_window = body[max(0, name_at - 200) : name_at + 200]
    assert 'aria-invalid="true"' in name_window, name_window
    # Fragment-only response — no page chrome leakage.
    assert "<!DOCTYPE" not in body
    assert "<html" not in body
    assert "Bedlam Connect" not in body


async def test_list_organizations_renders(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    create_resp = await authenticated_client.post("/organizations", data=_org_payload())
    assert create_resp.status_code == 201

    response = await authenticated_client.get("/organizations")
    assert response.status_code == 200
    assert "Acme Health" in response.text


async def test_detail_renders(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    create_resp = await authenticated_client.post("/organizations", data=_org_payload())
    new_id = uuid.UUID(create_resp.json()["id"])
    detail_resp = await authenticated_client.get(f"/organizations/{new_id}")
    assert detail_resp.status_code == 200
    assert "Acme Health" in detail_resp.text
    # Regression for #594 — the name appears in the header `<strong>`
    # only; the facts `<dl>` must not include a `<dt>Name</dt>` row
    # that duplicates the same string.
    assert "<dt>Name</dt>" not in detail_resp.text


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


async def test_get_organizations_form_resolves(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """Pins the create-form URL the templates link to.

    The grammar mandates ``GET /<collection>/form`` (not ``/new``). A
    prior set of clinician/program templates linked to ``/organizations/new``,
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


async def test_form_new_renders_minimal_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The minimal create form collects `name` + `npi` only. Other
    persisted fields are not surfaced on create — keeps onboarding minimal."""
    response = await authenticated_client.get("/organizations/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first('input[name="name"]') is not None
    assert tree.css_first('input[name="npi"]') is not None
    for absent in ("parent_org_id", "type"):
        assert (
            tree.css_first(f'[name="{absent}"]') is None
        ), f"{absent} should not appear on the minimal create form"


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


# --- Ownership-list subresource (intakes) --------------------------------


async def _seed_org_for(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    owner_id: uuid.UUID,
    name: str = "Intake Org",
) -> uuid.UUID:
    org = make_organization_row(owner_id=owner_id, name=name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(org)
    return org.id


async def _seed_program_intake(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    owner_id: uuid.UUID,
    org_id: uuid.UUID,
):
    """Persist a Program under `org_id` plus a Post(program_intake) whose
    IntakeDetail points at it."""
    from src.domain.models import Post
    from src.framework.persistence.base_repository import BaseRepository
    from tests.helpers import make_intake_detail, make_program

    async with db_test_session_manager() as session:
        async with session.begin():
            program = make_program(owner_id=owner_id, org_id=org_id)
            session.add(program)
        async with session.begin():
            post = Post(kind="program_intake", owner_id=owner_id)
            repo = BaseRepository(session)
            await repo.create_polymorphic(
                post,
                make_intake_detail(program_id=program.id),
                detail_relationship="intake_detail",
            )


async def test_get_org_intakes_empty_state(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /organizations/{id}/intakes` renders the empty state when the
    org's programs have no intakes posted."""
    org_id = await _seed_org_for(db_test_session_manager, owner_id=logged_in_user.id)
    response = await authenticated_client.get(f"/organizations/{org_id}/intakes")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("#org-intakes-list") is None
    empty = tree.css_first(".post-feed-empty")
    assert empty is not None
    assert "No program intakes posted" in empty.text()


async def test_get_org_intakes_lists_only_this_org(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The list scopes via Program.org_id: another org's intake does not
    bleed into this org's list."""
    mine = await _seed_org_for(
        db_test_session_manager, owner_id=logged_in_user.id, name="Mine"
    )
    other = await _seed_org_for(
        db_test_session_manager, owner_id=logged_in_user.id, name="Other"
    )
    await _seed_program_intake(
        db_test_session_manager, owner_id=logged_in_user.id, org_id=mine
    )
    await _seed_program_intake(
        db_test_session_manager, owner_id=logged_in_user.id, org_id=other
    )

    response = await authenticated_client.get(f"/organizations/{mine}/intakes")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert len(tree.css("#org-intakes-list .post-feed-row")) == 1


async def test_get_org_intakes_404_for_missing_org(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get(f"/organizations/{uuid.uuid4()}/intakes")
    assert response.status_code == 404


# --- Members subresource (org-side door onto the affiliation join, #1524) ---


async def _seed_member(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    owner_id: uuid.UUID,
    org_id: uuid.UUID,
    first_name: str = "Jane",
    last_name: str = "Smith",
) -> uuid.UUID:
    """Persist a Clinician at `org_id`. `make_clinician` builds the
    backing `ClinicianAffiliation` (org_id set, via the per-role proxy) —
    that affiliation row is exactly what the Members list scopes by.
    Returns the clinician id (the row's headline link target)."""
    async with db_test_session_manager() as session:
        async with session.begin():
            clinician = make_clinician(
                owner_id=owner_id,
                org_id=org_id,
                first_name=first_name,
                last_name=last_name,
            )
            session.add(clinician)
        return clinician.id


async def test_get_org_members_empty_state(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /organizations/{id}/members` renders the empty state when no
    clinician is affiliated with the org."""
    org_id = await _seed_org_for(db_test_session_manager, owner_id=logged_in_user.id)
    response = await authenticated_client.get(f"/organizations/{org_id}/members")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("#org-members-list") is None
    assert "No members yet" in response.text


async def test_get_org_members_lists_only_this_org(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The list scopes via `ClinicianAffiliation.org_id`: a member at
    another org does not bleed into this org's list, and the member's
    name + clinician-side edit link (the mutation door) render."""
    mine = await _seed_org_for(
        db_test_session_manager, owner_id=logged_in_user.id, name="Mine"
    )
    other = await _seed_org_for(
        db_test_session_manager, owner_id=logged_in_user.id, name="Other"
    )
    clinician_id = await _seed_member(
        db_test_session_manager,
        owner_id=logged_in_user.id,
        org_id=mine,
        first_name="Ada",
        last_name="Lovelace",
    )
    await _seed_member(
        db_test_session_manager,
        owner_id=logged_in_user.id,
        org_id=other,
        first_name="Grace",
        last_name="Hopper",
    )

    response = await authenticated_client.get(f"/organizations/{mine}/members")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#org-members-list article")
    assert len(rows) == 1, "members must scope to this org's affiliations"
    assert "Ada Lovelace" in response.text
    assert "Grace Hopper" not in response.text
    # Each row links to the clinician-side affiliation edit page — the
    # remove door. "One join, two doors."
    assert (
        f"/clinicians/{clinician_id}/clinician_affiliations/" in response.text
    ), "member row must link to the clinician-side edit (remove) page"


async def test_get_org_members_404_for_missing_org(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get(f"/organizations/{uuid.uuid4()}/members")
    assert response.status_code == 404


async def test_org_detail_links_to_members(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The org detail page surfaces a Members navigation link (the I6
    redesign's "members on the org page" intent)."""
    org_id = await _seed_org_for(db_test_session_manager, owner_id=logged_in_user.id)
    response = await authenticated_client.get(f"/organizations/{org_id}")
    assert response.status_code == 200
    assert f"/organizations/{org_id}/members" in response.text


# --- Network-aware redaction -------------------------------------------------


async def test_list_200_for_unverified_viewer_redacts_others(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`/organizations` is reachable for every authenticated viewer; a
    viewer without provider-network access sees rows they don't own or
    rep with the identifying fields (name, NPI) replaced by `locked_name`
    / `locked_field` placeholders. The viewer is `logged_in_user` and
    `other_owner` owns the row, so the redaction must fire."""
    other_owner = create_test_user(username=f"other-{uuid.uuid4()}")
    org_name = f"Stranger Health {uuid.uuid4()}"
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other_owner)
            session.add(make_organization_row(owner_id=other_owner.id, name=org_name))

    response = await authenticated_client.get("/organizations")
    assert response.status_code == 200
    assert org_name not in response.text
    # `locked_name` renders a button containing the placeholder; the page
    # therefore signals "row exists, identity withheld".
    assert "Doe Health Group" in response.text


async def test_list_200_for_owner_renders_own_row_unredacted(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The viewer's own org renders un-redacted on `/organizations` even
    when they lack `can_act_as_provider` — owners must be able to manage
    what they've created before clearing network verification.

    Self-registering an organization also grants the creator a verified
    `OrgRepresentation`, which flips `can_act_as_provider` to True; the
    test pins the post-create state where the row is visible by name."""
    create = await authenticated_client.post("/organizations", data=_org_payload())
    assert create.status_code == 201

    response = await authenticated_client.get("/organizations")
    assert response.status_code == 200
    assert "Acme Health" in response.text


# --- ?owner=me filter --------------------------------------------------------


async def test_list_owner_me_scopes_to_viewer_owned_orgs(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """``?owner=me`` filters the directory to orgs the viewer is
    affiliated with (owned OR holds a verified rep for). Seed one
    stranger-owned org + one viewer-owned org directly via the DB
    (bypassing the NPPES create gate, which is exercised separately);
    the filtered response must include the viewer's own row and
    exclude the stranger's."""
    other_owner = create_test_user(username=f"other-{uuid.uuid4()}")
    stranger_name = f"Stranger Health {uuid.uuid4()}"
    own_name = f"My Health {uuid.uuid4()}"
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other_owner)
            session.add(
                make_organization_row(owner_id=other_owner.id, name=stranger_name)
            )
            session.add(
                make_organization_row(owner_id=logged_in_user.id, name=own_name)
            )

    response = await authenticated_client.get("/organizations?owner=me")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#organizations-list article")
    assert len(rows) == 1, "?owner=me must return only the viewer's own row"
    assert own_name in response.text
    assert stranger_name not in response.text
