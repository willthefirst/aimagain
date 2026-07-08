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


async def test_create_program_form_error_render_is_wired(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Integration smoke for `PROGRAM_ENTITY.form_error_render`.

    HX-Request POST with an empty `name` trips the schema's
    min-length → 422 + HTML fragment with the inline error on the
    `name` input. Same shape as the organizations smoke; rationale
    in `test_post_families.py::test_clinician_opening_create_form_error_render_is_wired`.
    """
    org_id = await _seed_org(db_test_session_manager, owner_id=logged_in_user.id)
    response = await authenticated_client.post(
        "/programs",
        data=_program_payload(org_id=org_id, name=""),
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    name_at = body.index('name="name"')
    name_window = body[max(0, name_at - 200) : name_at + 200]
    assert 'aria-invalid="true"' in name_window, name_window
    assert "<!DOCTYPE" not in body
    assert "<html" not in body
    assert "Bedlam Connect" not in body


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


async def test_list_programs_empty_state_has_inline_create_cta(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """When no programs exist for the viewer, the empty state itself
    pulls the eye to the next action — a "Create program" button inline,
    not just the toolbar one above. Pins #598 so the CTA can't silently
    regress to a bare "No programs found." paragraph.
    """
    response = await authenticated_client.get("/programs")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    empty = tree.css_first("#programs-empty-state")
    assert empty is not None, "empty-state container missing"

    cta = empty.css_first("a[role='button']")
    assert cta is not None, "inline Create CTA missing from empty state"
    assert "Create program" in cta.text()
    assert cta.attributes.get("href") == "/programs/form"


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


async def test_form_edit_renders_save_cancel_delete_cluster(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Edit pages render the standardized `form_actions` cluster with
    Save (submit), Cancel (plain muted link to detail), and Delete
    (hx-delete with confirm). Delete carries the `form-actions-destructive`
    class so the CSS isolates it on the far left of the cluster, separated
    from the right-aligned confirm actions."""
    org_id = await _seed_org(db_test_session_manager, owner_id=logged_in_user.id)
    program_id = await _seed_program_for(
        db_test_session_manager, owner_id=logged_in_user.id, org_id=org_id
    )
    response = await authenticated_client.get(f"/programs/{program_id}/form")
    tree = HTMLParser(response.text)
    cluster = tree.css_first(".form-actions")
    assert cluster is not None
    assert cluster.css_first('button[type="submit"]') is not None
    cancel = cluster.css_first(f'a[href="/programs/{program_id}"].secondary')
    assert cancel is not None
    assert (
        cancel.attributes.get("role") != "button"
    ), "Cancel is a plain muted link (Pico `class=secondary`), not a button"
    assert cancel.text(strip=True) == "Cancel"
    delete = cluster.css_first(f'button[hx-delete="/programs/{program_id}"]')
    assert delete is not None
    assert "form-actions-destructive" in (delete.attributes.get("class") or "")
    assert delete.attributes.get("hx-confirm")


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


# --- Steady-state context UI (website / referral instructions) ----------
#
# The per-announcement profile (services / settings / modalities /
# age_groups / genders) moved off Program onto IntakeDetail. What
# remains on the program form / detail page is the steady-state context:
# `website` and `referral_instructions`. These tests pin the render
# contract (each field has an input on the form, each set value renders
# on the detail page) and the round-trip (POST/PATCH persists, GET
# surfaces).


async def test_form_new_renders_context_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Each context field renders at least one input/textarea on the
    create form. Asserts by `name=` because that's the wire contract."""
    await _seed_org(db_test_session_manager, owner_id=logged_in_user.id)
    response = await authenticated_client.get("/programs/form")
    assert response.status_code == 200
    body = response.text
    for field in ("website", "referral_instructions"):
        assert f'name="{field}"' in body, f"missing input for {field}"


async def test_form_edit_renders_context_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    org_id = await _seed_org(db_test_session_manager, owner_id=logged_in_user.id)
    program_id = await _seed_program_for(
        db_test_session_manager, owner_id=logged_in_user.id, org_id=org_id
    )
    response = await authenticated_client.get(f"/programs/{program_id}/form")
    assert response.status_code == 200
    body = response.text
    for field in ("website", "referral_instructions"):
        assert f'name="{field}"' in body, f"missing input for {field}"


async def test_form_edit_pre_fills_persisted_context_values(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Context fields that were previously saved render pre-filled."""
    org_id = await _seed_org(db_test_session_manager, owner_id=logged_in_user.id)
    program = Program(
        owner_id=logged_in_user.id,
        org_id=org_id,
        name="Profiled IOP",
        website="https://example.com/intake",
        referral_instructions="Email intake@example.com.",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(program)
        await session.refresh(program)

    response = await authenticated_client.get(f"/programs/{program.id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    website_input = tree.css_first('input[name="website"]')
    assert website_input is not None
    assert website_input.attributes.get("value") == "https://example.com/intake"
    instructions = tree.css_first('textarea[name="referral_instructions"]')
    assert instructions is not None
    assert "Email intake@example.com." in instructions.text()


async def test_create_program_persists_context(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """POST the context fields (plus a list-valued `languages`) end-to-end;
    the row carries every value."""
    org_id = await _seed_org(db_test_session_manager, owner_id=logged_in_user.id)
    payload = _program_payload(
        org_id=org_id,
        languages=["en", "es"],
        website="https://example.com",
        referral_instructions="Call intake.",
    )
    # `httpx.AsyncClient.post(data=...)` form-encodes lists by repeating
    # the key — same shape an HTML multi-checkbox form posts.
    response = await authenticated_client.post("/programs", data=payload)
    assert response.status_code == 201, response.text
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        loaded = await session.get(Program, new_id)
        assert loaded is not None
        assert loaded.languages == ["en", "es"]
        assert loaded.website == "https://example.com"
        assert loaded.referral_instructions == "Call intake."


async def test_patch_updates_context(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """PATCH context fields (one free-text, one list-valued); the row is
    updated. Mirrors `test_patch_updates_name`."""
    org_id = await _seed_org(db_test_session_manager, owner_id=logged_in_user.id)
    program_id = await _seed_program_for(
        db_test_session_manager, owner_id=logged_in_user.id, org_id=org_id
    )
    response = await authenticated_client.patch(
        f"/programs/{program_id}",
        data={"languages": ["es"], "website": "https://updated.example"},
    )
    assert response.status_code in (200, 204)

    async with db_test_session_manager() as session:
        loaded = await session.get(Program, program_id)
        assert loaded is not None
        assert loaded.languages == ["es"]
        assert loaded.website == "https://updated.example"


async def test_detail_renders_context(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Persisted context fields surface as facts rows on the detail page,
    keyed by their stable `data-fact` selectors."""
    org_id = await _seed_org(db_test_session_manager, owner_id=logged_in_user.id)
    program = Program(
        owner_id=logged_in_user.id,
        org_id=org_id,
        name="Detail Profiled",
        website="https://example.com",
        referral_instructions="Email intake@example.com.",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(program)
        await session.refresh(program)

    response = await authenticated_client.get(f"/programs/{program.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    for key in ("website", "referral_instructions"):
        assert (
            tree.css_first(f'[data-fact="{key}"]') is not None
        ), f"missing fact row for {key}"


async def test_detail_omits_empty_context_facts(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A Program with no context values rendered today (the model
    defaults are NULL free-text) skips every context row."""
    org_id = await _seed_org(db_test_session_manager, owner_id=logged_in_user.id)
    program_id = await _seed_program_for(
        db_test_session_manager, owner_id=logged_in_user.id, org_id=org_id
    )
    response = await authenticated_client.get(f"/programs/{program_id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    for key in ("website", "referral_instructions"):
        assert (
            tree.css_first(f'[data-fact="{key}"]') is None
        ), f"unexpected empty-state row for {key}"
