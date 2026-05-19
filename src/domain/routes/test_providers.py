import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import (
    Provider,
    ProviderCertification,
    ProviderEducation,
    ProviderLicensure,
    User,
)
from src.framework.audit.repository import AuditRepository
from tests.helpers import (
    create_test_user,
    make_organization_row,
    make_provider_certification,
    make_provider_education,
    make_provider_licensure,
    make_provider_with_org,
    promote_to_admin,
    provider_payload,
)

pytestmark = pytest.mark.asyncio


# --- Helpers -------------------------------------------------------------


async def _seed_org(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    owner_id: uuid.UUID,
    name: str = "Acme Therapy",
) -> uuid.UUID:
    """Insert a root Organization and return its id. Used by tests that
    POST to ``/providers`` — the wire schema requires ``org_id`` (#524)
    so each create test needs an Org persisted up front."""
    org = make_organization_row(owner_id=owner_id, name=name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(org)
    return org.id


async def _seed_provider_for(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    **overrides,
) -> uuid.UUID:
    """Insert a provider owned by `user_id` and return its id."""
    provider = make_provider_with_org(owner_id=user_id, **overrides)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)
        await session.refresh(provider)
        return provider.id


async def _clinician_id_for(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    provider_id: uuid.UUID,
) -> uuid.UUID:
    """Look up the `clinician_id` for a previously-seeded provider —
    credential sub-tables FK to `clinicians.id` after #635 PR A, but
    test fixtures still carry `provider_id` around. One small lookup
    bridges the two."""
    async with db_test_session_manager() as session:
        return (
            await session.execute(
                select(Provider.clinician_id).where(Provider.id == provider_id)
            )
        ).scalar_one()


async def _seed_other_user_with_provider(
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a second user + their provider. Returns (user_id, provider_id)."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    provider_id = await _seed_provider_for(db_test_session_manager, user_id=other.id)
    return other.id, provider_id


async def _audit_rows_for(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    resource_type: str,
    resource_id: uuid.UUID,
):
    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        return await repo.list_for_resource(
            resource_type=resource_type, resource_id=resource_id
        )


# --- Provider create ------------------------------------------------------


async def test_create_provider_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """POST /providers with a form-encoded body returns 201 + id and
    persists the provider and an audit row."""
    org_id = await _seed_org(
        db_test_session_manager, owner_id=logged_in_user.id, name="Acme Therapy"
    )
    response = await authenticated_client.post(
        "/providers",
        data=provider_payload(org_id=str(org_id)),
    )

    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])
    assert response.headers["Location"] == f"/providers/{new_id}"
    assert response.headers["HX-Redirect"] == f"/providers/{new_id}/form"

    async with db_test_session_manager() as session:
        result = await session.execute(select(Provider).filter(Provider.id == new_id))
        persisted = result.scalars().first()
        assert persisted is not None
        assert persisted.owner_id == logged_in_user.id
        assert persisted.org_id == org_id
        assert persisted.org.name == "Acme Therapy"

    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider",
        resource_id=new_id,
    )
    assert len(rows) == 1
    assert rows[0].action == "create_provider"
    assert rows[0].actor_id == logged_in_user.id


async def test_create_provider_allows_multiple_per_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A user may own multiple providers. Two successive POSTs both
    return 201 and persist as distinct rows owned by the same user."""
    org_first = await _seed_org(
        db_test_session_manager, owner_id=logged_in_user.id, name="First"
    )
    org_second = await _seed_org(
        db_test_session_manager, owner_id=logged_in_user.id, name="Second"
    )
    first = await authenticated_client.post(
        "/providers", data=provider_payload(org_id=str(org_first))
    )
    assert first.status_code == 201
    first_id = uuid.UUID(first.json()["id"])

    second = await authenticated_client.post(
        "/providers", data=provider_payload(org_id=str(org_second))
    )
    assert second.status_code == 201
    second_id = uuid.UUID(second.json()["id"])

    assert first_id != second_id

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(Provider).filter(Provider.owner_id == logged_in_user.id)
        )
        owned = result.scalars().all()
        assert {p.id for p in owned} == {first_id, second_id}
        assert {p.org.name for p in owned} == {"First", "Second"}


async def test_create_provider_rejects_org_owned_by_another_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Attaching a Provider is permissioned by Org ownership (#524). A
    user POSTing with another user's `org_id` is forbidden — 403 keeps
    the boundary visible (the dropdown wouldn't have surfaced this Org
    in the first place; this guard catches curl callers)."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    other_org_id = await _seed_org(
        db_test_session_manager, owner_id=other.id, name="Other's Org"
    )

    response = await authenticated_client.post(
        "/providers", data=provider_payload(org_id=str(other_org_id))
    )
    assert response.status_code == 403


async def test_create_provider_rejects_nonexistent_org(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """A POST with an `org_id` that doesn't exist returns 404 — no
    leak about other users' Org ids, and avoids the 500 the DB FK
    would otherwise produce."""
    bogus = uuid.uuid4()
    response = await authenticated_client.post(
        "/providers", data=provider_payload(org_id=str(bogus))
    )
    assert response.status_code == 404


async def test_create_provider_allows_superuser_to_attach_to_any_org(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Superusers bypass the Org-ownership check — mirrors the
    `OWNER_OR_ADMIN` policy on the Org row itself."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    other_org_id = await _seed_org(
        db_test_session_manager, owner_id=other.id, name="Other's Org"
    )

    response = await authenticated_client.post(
        "/providers", data=provider_payload(org_id=str(other_org_id))
    )
    assert response.status_code == 201


# --- Provider reads -------------------------------------------------------


async def test_get_provider_renders_detail_page(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /providers/{id}` renders the read-only HTML detail page
    with practice fields and an Edit link for the owner."""
    provider_id = await _seed_provider_for(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Mine"
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, provider_id)
    licensure = make_provider_licensure(
        clinician_id=clinician_id, license_type="lcsw", license_number="L-99999"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(licensure)

    response = await authenticated_client.get(f"/providers/{provider_id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    tree = HTMLParser(response.text)
    # Licensure section renders the seeded row.
    assert "L-99999" in response.text
    # Owner sees an Edit link, no edit forms (read-only).
    assert tree.css_first(f'a[href="/providers/{provider_id}/form"]') is not None
    assert tree.css_first("form") is None
    # Regression for #594 — the practice name lives in the header
    # `<strong>` only. The facts list relabels its row "Organization"
    # so the same string is not repeated under a "Practice name" `<dt>`.
    assert "<dt>Practice name</dt>" not in response.text


async def test_get_provider_hides_edit_link_for_non_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A non-owner viewing someone else's provider sees the detail content
    but no Edit link."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    provider_id = await _seed_provider_for(db_test_session_manager, user_id=other.id)

    response = await authenticated_client.get(f"/providers/{provider_id}")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first(f'a[href="/providers/{provider_id}/form"]') is None


def _delete_provider_button(tree: HTMLParser, provider_id: uuid.UUID):
    return tree.css_first(f'button[hx-delete="/providers/{provider_id}"]')


async def test_get_provider_renders_delete_button_for_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The owner's detail view carries a Delete button in the toolbar
    actions alongside Edit. The button is an `hx-delete` confirm button
    (per `_shared/actions.html::confirm_delete_button`)."""
    provider_id = await _seed_provider_for(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Mine"
    )

    response = await authenticated_client.get(f"/providers/{provider_id}")
    tree = HTMLParser(response.text)
    button = _delete_provider_button(tree, provider_id)
    assert button is not None
    assert "Delete" in button.text()
    assert button.attributes.get("hx-confirm")


async def test_get_provider_hides_delete_button_for_non_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A non-owner viewing another user's provider sees neither the Edit
    link nor the Delete button — both gated on `can_edit`."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    provider_id = await _seed_provider_for(db_test_session_manager, user_id=other.id)

    response = await authenticated_client.get(f"/providers/{provider_id}")
    tree = HTMLParser(response.text)
    assert _delete_provider_button(tree, provider_id) is None


# --- Provider listing -----------------------------------------------------


async def test_list_providers_renders_html(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`GET /providers` renders an HTML page with one entry per
    persisted provider, regardless of which user owns it."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    provider_id = await _seed_provider_for(
        db_test_session_manager, user_id=other.id, practice_name="Open House"
    )

    response = await authenticated_client.get("/providers")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    tree = HTMLParser(response.text)
    rows = tree.css("#providers-table tbody tr")
    assert len(rows) == 1
    assert tree.css_first(f'a[href="/providers/{provider_id}"]') is not None
    assert "Open House" in response.text


async def test_list_providers_shows_licensure_states(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Each list row surfaces the provider's licensure issuing states in
    its "Licensed in" cell so matches against `?issuing_state=` are
    visually obvious — a CT-located provider holding a CA license shows
    `CA, CT` and the user can see why they appeared in a CA filter
    (#458 follow-up)."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    provider_id = await _seed_provider_for(
        db_test_session_manager,
        user_id=other.id,
        practice_name="Multi-state Care",
        location_state="CT",
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, provider_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                make_provider_licensure(
                    clinician_id=clinician_id,
                    license_type="lcsw",
                    issuing_state="CA",
                )
            )
            session.add(
                make_provider_licensure(
                    clinician_id=clinician_id,
                    license_type="lpc",
                    issuing_state="CT",
                )
            )

    response = await authenticated_client.get("/providers")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    licensed_in_cell = tree.css_first(
        f'tr[data-row-id="{provider_id}"] td[data-label="Licensed in"]'
    )
    assert licensed_in_cell is not None
    assert licensed_in_cell.text(strip=True) == "CA, CT"


async def test_list_providers_renders_create_toolbar_action(
    authenticated_client: AsyncClient,
):
    """`/providers` (Directory) carries a 'Create provider' toolbar
    button — matches the orgs/programs/posts list convention so an
    authenticated user always has a discoverable Create entry point.
    The route's auth is `AUTHENTICATED` (creation is not gated to
    owners/admins), so the button shows to every authenticated viewer."""
    response = await authenticated_client.get("/providers")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    action = None
    for anchor in tree.css('menu.toolbar-right > li > a[role="button"]'):
        if "Create provider" in (anchor.text() or ""):
            action = anchor
            break
    assert action is not None, "Create provider toolbar action is missing on /providers"
    assert action.attributes.get("href") == "/providers/form"


async def test_list_providers_renders_empty_state(
    authenticated_client: AsyncClient,
):
    """With no persisted providers, the page renders a friendly empty
    message instead of an empty `<table>`. The list page's toolbar
    links to `/providers/search`; the multi-choice filter widgets live
    there, not on the list page."""
    response = await authenticated_client.get("/providers")
    assert response.status_code == 200
    assert "No providers found" in response.text
    tree = HTMLParser(response.text)
    assert tree.css_first("#providers-table") is None
    # Filter link goes to the dedicated search page.
    link = tree.css_first("a.toolbar-filter-link")
    assert link is not None
    assert (link.attributes.get("href") or "").startswith("/providers/search")
    # The filter widgets live on the search page — multi-choice
    # `ChoiceFilter`s now render as a `<fieldset>` of single-click
    # checkboxes (#583), not the previous native `<select multiple>`
    # listbox. No checkbox is preselected when the filter is inactive.
    search_response = await authenticated_client.get("/providers/search")
    assert search_response.status_code == 200
    search_tree = HTMLParser(search_response.text)
    for filter_name in ("license_type", "issuing_state"):
        boxes = search_tree.css(f'input[type="checkbox"][name="{filter_name}"]')
        assert boxes, f"{filter_name} should render at least one checkbox"
        assert not any(
            "checked" in b.attributes for b in boxes
        ), f"{filter_name} should have no preselected checkbox when filter is inactive"
    # The legacy `<select multiple>` listbox should be gone from the
    # search form — the regression this guards is "checkbox swap
    # forgot to remove the old control".
    assert search_tree.css_first("form.search-form select[multiple]") is None


async def test_list_providers_filters_by_license_type(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`?license_type=` keeps only providers holding a matching licensure;
    the filter form preselects the active value."""
    user_a = create_test_user(username=f"ua-{uuid.uuid4()}")
    user_b = create_test_user(username=f"ub-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user_a)
            session.add(user_b)
    provider_a = await _seed_provider_for(
        db_test_session_manager, user_id=user_a.id, practice_name="A clinic"
    )
    provider_b = await _seed_provider_for(
        db_test_session_manager, user_id=user_b.id, practice_name="B clinic"
    )
    clinician_a = await _clinician_id_for(db_test_session_manager, provider_a)
    clinician_b = await _clinician_id_for(db_test_session_manager, provider_b)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                make_provider_licensure(clinician_id=clinician_a, license_type="psyd")
            )
            session.add(
                make_provider_licensure(clinician_id=clinician_b, license_type="lcsw")
            )

    response = await authenticated_client.get("/providers?license_type=psyd")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#providers-table tbody tr")
    assert len(rows) == 1
    assert tree.css_first(f'a[href="/providers/{provider_a}"]') is not None
    assert tree.css_first(f'a[href="/providers/{provider_b}"]') is None
    # The toolbar's filter link summarizes the active filter inline.
    link = tree.css_first("a.toolbar-filter-link")
    assert link is not None
    link_text = link.text()
    assert "psyd" in link_text.lower() or "PsyD" in link_text
    # The search page re-renders the form with the active value preselected.
    # Multi-choice filters now render as checkboxes (#583), so the
    # active value surfaces as a `checked` `<input type="checkbox">`.
    search = await authenticated_client.get("/providers/search?license_type=psyd")
    assert search.status_code == 200
    checked = HTMLParser(search.text).css_first(
        'input[type="checkbox"][name="license_type"][value="psyd"]'
    )
    assert checked is not None
    assert "checked" in checked.attributes


async def test_list_providers_treats_empty_filter_values_as_absent(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Pressing "Apply" on the filter form with no selection submits
    `?license_type=&issuing_state=` — empty values, not absent. The
    `StripEmptyQueryParamsMiddleware` removes those pairs at request
    entry so the route's declared defaults fire and every provider
    renders, the same as visiting `/providers` with no query string.
    Without the middleware the empty strings reach the repo's filter
    and zero rows match (the bug this regression test guards)."""
    other = create_test_user(username=f"empty-filter-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    await _seed_provider_for(
        db_test_session_manager, user_id=other.id, practice_name="Filter Test"
    )

    response = await authenticated_client.get("/providers?license_type=&issuing_state=")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#providers-table tbody tr")
    assert len(rows) == 1, "Empty filter values should not exclude rows"


# --- Chrome: toolbar + form affordances --------------------------------


async def test_providers_list_toolbar_renders_filter_link_and_create_action(
    authenticated_client: AsyncClient,
):
    """`/providers` toolbar carries both the filter link (left) and a
    'Create provider' action (right). The Create button matches the
    orgs/programs/posts list-page convention; the dedicated
    `test_list_providers_renders_create_toolbar_action` test above
    pins the action's `href` shape — this one pins the toolbar
    composition (filter ✕ actions both present)."""
    response = await authenticated_client.get("/providers")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("a.toolbar-filter-link") is not None
    action_menu = tree.css_first("menu.toolbar-right")
    assert action_menu is not None
    assert "Create provider" in action_menu.text()


async def test_provider_detail_favorite_toggle_lives_in_toolbar(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The favorite/unfavorite button is a primary resource action and
    renders inside the toolbar, not in `<footer>` or `<article>`. Pins
    the chrome rule in `src/framework/templates/README.md`."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    provider_id = await _seed_provider_for(db_test_session_manager, user_id=other.id)

    response = await authenticated_client.get(f"/providers/{provider_id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    favorite_selector = f'button[hx-post="/users/me/favorites/{provider_id}"]'
    assert tree.css_first(f".toolbar {favorite_selector}") is not None
    # The favorite button is not duplicated inside <article>.
    assert tree.css_first(f"article {favorite_selector}") is None


async def test_provider_form_new_renders_form_actions_cluster(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /providers/form` renders the standardized Save/Cancel
    cluster (the `form_actions` macro). Cancel on the create page
    points at the collection so a user can bail without leaving the
    app's resource scope — matches the edit page's bottom Cancel."""
    response = await authenticated_client.get("/providers/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    actions = tree.css_first(".form-actions")
    assert actions is not None
    cancel = tree.css_first('.form-actions a[href="/providers"][role="button"]')
    assert cancel is not None
    assert cancel.text(strip=True) == "Cancel"


async def test_provider_form_edit_renders_cancel(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /providers/{id}/form` keeps a bottom "Cancel" link pointing
    at the detail page (a deliberate "abandon this edit" affordance —
    see `src/framework/templates/README.md`)."""
    provider_id = await _seed_provider_for(
        db_test_session_manager,
        user_id=logged_in_user.id,
        practice_name="Edit Me",
    )
    response = await authenticated_client.get(f"/providers/{provider_id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    cancel = tree.css_first(f'a[href="/providers/{provider_id}"][role="button"]')
    assert cancel is not None
    assert cancel.text(strip=True) == "Cancel"


# --- Provider update ------------------------------------------------------


async def test_patch_provider_updates_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """PATCH /providers/{id} can reassign the Provider to a different Org
    (``org_id``) or change other practice fields like location. Editing
    the practice's *name* now happens on the Organization itself (#524)."""
    provider_id = await _seed_provider_for(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Old Name"
    )
    new_org_id = await _seed_org(
        db_test_session_manager, owner_id=logged_in_user.id, name="New Org"
    )

    response = await authenticated_client.patch(
        f"/providers/{provider_id}",
        data={"org_id": str(new_org_id)},
    )

    assert response.status_code == 200
    assert response.json()["org_id"] == str(new_org_id)
    assert response.headers["HX-Redirect"] == f"/providers/{provider_id}/form"

    async with db_test_session_manager() as session:
        refreshed = (
            (await session.execute(select(Provider).filter(Provider.id == provider_id)))
            .scalars()
            .first()
        )
        assert refreshed.org_id == new_org_id


async def test_patch_provider_returns_403_if_not_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    _, other_provider_id = await _seed_other_user_with_provider(db_test_session_manager)
    new_org_id = await _seed_org(
        db_test_session_manager, owner_id=logged_in_user.id, name="Hijack Org"
    )

    response = await authenticated_client.patch(
        f"/providers/{other_provider_id}",
        data={"org_id": str(new_org_id)},
    )
    assert response.status_code == 403


async def test_patch_provider_rejects_reassign_to_unowned_org(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A PATCH that swaps ``org_id`` to another user's Org is forbidden
    — same boundary as create (#524)."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    other_org_id = await _seed_org(
        db_test_session_manager, owner_id=other.id, name="Not Mine"
    )
    provider_id = await _seed_provider_for(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Mine"
    )

    response = await authenticated_client.patch(
        f"/providers/{provider_id}",
        data={"org_id": str(other_org_id)},
    )
    assert response.status_code == 403


# --- Provider delete ------------------------------------------------------


async def test_delete_provider_returns_204_and_leaves_credentials(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """After #635 PR A, credentials FK to `clinicians.id`. Deleting a
    Provider returns 204 but leaves the person-level credentials attached
    to the Clinician (which survives — Provider→Clinician is RESTRICT)."""
    provider_id = await _seed_provider_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, provider_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(make_provider_licensure(clinician_id=clinician_id))
            session.add(make_provider_education(clinician_id=clinician_id))
            session.add(make_provider_certification(clinician_id=clinician_id))

    response = await authenticated_client.delete(f"/providers/{provider_id}")
    assert response.status_code == 204

    async with db_test_session_manager() as session:
        assert (
            await session.execute(select(Provider).filter(Provider.id == provider_id))
        ).scalars().first() is None
        # Credentials stay attached to the Clinician.
        assert (
            await session.execute(
                select(ProviderLicensure).filter(
                    ProviderLicensure.clinician_id == clinician_id
                )
            )
        ).scalars().first() is not None
        assert (
            await session.execute(
                select(ProviderEducation).filter(
                    ProviderEducation.clinician_id == clinician_id
                )
            )
        ).scalars().first() is not None
        assert (
            await session.execute(
                select(ProviderCertification).filter(
                    ProviderCertification.clinician_id == clinician_id
                )
            )
        ).scalars().first() is not None


# --- Licensure sub-resource ---------------------------------------------


async def test_patch_licensure_updates_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    provider_id = await _seed_provider_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, provider_id)
    licensure = make_provider_licensure(clinician_id=clinician_id, license_number="L-1")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(licensure)
        await session.refresh(licensure)
        licensure_id = licensure.id

    response = await authenticated_client.patch(
        f"/providers/{provider_id}/licensures/{licensure_id}",
        data={"license_number": "L-2"},
    )

    assert response.status_code == 200
    assert response.json()["license_number"] == "L-2"


async def test_patch_licensure_returns_404_for_mismatched_provider(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A licensure_id that belongs to a different provider must 404, not silently
    update across provider boundaries."""
    my_provider_id = await _seed_provider_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    _, other_provider_id = await _seed_other_user_with_provider(db_test_session_manager)
    other_clinician_id = await _clinician_id_for(
        db_test_session_manager, other_provider_id
    )
    other_licensure = make_provider_licensure(clinician_id=other_clinician_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other_licensure)
        await session.refresh(other_licensure)
        other_licensure_id = other_licensure.id

    response = await authenticated_client.patch(
        f"/providers/{my_provider_id}/licensures/{other_licensure_id}",
        data={"license_number": "stolen"},
    )
    assert response.status_code == 404


# --- Education / certification happy paths ------------------------------


# --- Create form page (GET /providers/form) ----------------------


async def test_get_provider_form_renders(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /providers/form` renders the create form posting to
    the JSON API."""
    # Seed an Org so the Org-picker dropdown has at least one option to render.
    await _seed_org(
        db_test_session_manager, owner_id=logged_in_user.id, name="Seeded Org"
    )
    response = await authenticated_client.get("/providers/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    form = tree.css_first("form")
    assert form is not None
    assert form.attributes.get("hx-post") == "/providers"
    # Org-picker dropdown — replaces the old free-text practice_name input.
    # Lists the Orgs the requesting user owns (#524).
    org_select = tree.css_first('select[name="org_id"]')
    assert org_select is not None
    org_options = org_select.css("option")
    assert any(
        o.text(strip=True) == "Seeded Org" for o in org_options
    ), "Org dropdown should include every Org the user owns"
    city = tree.css_first('input[name="location_city"]')
    assert city is not None
    assert city.attributes.get("maxlength") == "120"
    zip_input = tree.css_first('input[name="location_zip"]')
    assert zip_input is not None
    assert zip_input.attributes.get("pattern") == r"\d{5}"
    assert zip_input.attributes.get("maxlength") == "5"
    # State select with all 51 entries (50 states + DC) plus a placeholder.
    state_select = tree.css_first('select[name="location_state"]')
    assert state_select is not None
    state_options = state_select.css("option")
    assert len(state_options) == 52  # 51 + placeholder
    # Availability selects with three real options + placeholder.
    in_person = tree.css_first('select[name="in_person_sessions"]')
    virtual = tree.css_first('select[name="virtual_sessions"]')
    assert in_person is not None
    assert virtual is not None
    assert len(in_person.css("option")) == 4
    assert len(virtual.css("option")) == 4
    # Insurance & payment fieldset. The carrier multi-select speaks for
    # the in-network signal (empty = no in-network); only OON and
    # sliding-scale render as bool radios.
    assert tree.css_first('input[type="radio"][name="accepts_in_network"]') is None
    assert (
        tree.css_first('input[type="radio"][name="accepts_out_of_network"]') is not None
    )
    assert tree.css_first('input[type="radio"][name="sliding_scale"]') is not None
    assert tree.css_first('input[name="cost"]') is not None
    carrier_select = tree.css_first('select[name="in_network_carriers"][multiple]')
    assert carrier_select is not None
    assert len(carrier_select.css("option")) == 11


async def test_get_provider_form_scopes_org_dropdown_to_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The Org dropdown lists only the requesting user's Orgs (#524).
    Another user's Org must not leak into the picker."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    await _seed_org(db_test_session_manager, owner_id=logged_in_user.id, name="Mine")
    await _seed_org(db_test_session_manager, owner_id=other.id, name="Theirs")

    response = await authenticated_client.get("/providers/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    option_texts = {
        o.text(strip=True) for o in tree.css('select[name="org_id"] option')
    }
    assert "Mine" in option_texts
    assert "Theirs" not in option_texts


# --- Edit form page (GET /providers/{id}/form) -------------------


async def test_owner_can_open_edit_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Owner sees the edit form pre-filled with provider fields and any
    existing credential sub-rows."""
    provider_id = await _seed_provider_for(
        db_test_session_manager,
        user_id=logged_in_user.id,
        practice_name="Acme Counseling",
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, provider_id)
    licensure = make_provider_licensure(
        clinician_id=clinician_id, license_type="lcsw", license_number="L-12345"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(licensure)

    response = await authenticated_client.get(f"/providers/{provider_id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    org_select = tree.css_first('select[name="org_id"]')
    assert org_select is not None
    selected = org_select.css_first("option[selected]")
    assert selected is not None
    assert selected.text(strip=True) == "Acme Counseling"
    practice_form = tree.css_first(f'form[hx-patch="/providers/{provider_id}"]')
    assert practice_form is not None
    # The seeded licensure should be rendered in the licensures list.
    assert "L-12345" in response.text
    # Sub-section add forms target the right URLs.
    assert (
        tree.css_first(f'form[hx-post="/providers/{provider_id}/licensures"]')
        is not None
    )
    assert (
        tree.css_first(f'form[hx-post="/providers/{provider_id}/educations"]')
        is not None
    )
    assert (
        tree.css_first(f'form[hx-post="/providers/{provider_id}/certifications"]')
        is not None
    )


async def test_owner_edit_form_renders_credentials_as_rows(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Credential lists render as `.credential-row` blocks (not raw
    `<li>`s) — bold type label, muted meta line, owner-side Delete
    button. The owning `<section>` already provides the framing; rows
    stay flat to avoid the card-on-card look."""
    provider_id = await _seed_provider_for(
        db_test_session_manager,
        user_id=logged_in_user.id,
        practice_name="Acme Counseling",
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, provider_id)
    licensure = make_provider_licensure(
        clinician_id=clinician_id,
        license_type="lcsw",
        license_number="L-12345",
        issuing_state="CA",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(licensure)

    response = await authenticated_client.get(f"/providers/{provider_id}/form")
    tree = HTMLParser(response.text)
    rows = tree.css(".credential-list .credential-row")
    assert len(rows) >= 1
    first = rows[0]
    assert (
        first.css_first("strong").text(strip=True)
        == "Licensed Clinical Social Worker (LCSW)"
    )
    meta = first.css_first(".credential-row-text small")
    assert meta is not None
    assert "L-12345" in meta.text()
    assert "CA" in meta.text()
    delete = first.css_first(
        f'button[hx-delete="/providers/{provider_id}/licensures/{licensure.id}"]'
    )
    assert delete is not None
    assert delete.text(strip=True) == "Delete"


async def test_admin_can_open_edit_form_for_any_provider(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    _other_user_id, provider_id = await _seed_other_user_with_provider(
        db_test_session_manager
    )
    response = await authenticated_client.get(f"/providers/{provider_id}/form")
    assert response.status_code == 200


async def test_non_owner_cannot_open_edit_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    _other_user_id, provider_id = await _seed_other_user_with_provider(
        db_test_session_manager
    )
    response = await authenticated_client.get(f"/providers/{provider_id}/form")
    assert response.status_code == 403


# --- Pagination ---------------------------------------------------------


async def test_list_renders_no_pagination_footer_for_single_page(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A result that fits on a single page renders no Prev/Next chrome.
    Pins the `pagination` macro's single-page suppression rule."""
    await _seed_provider_for(db_test_session_manager, user_id=logged_in_user.id)
    response = await authenticated_client.get("/providers")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first('nav[aria-label="Pagination"]') is None


async def test_list_paginates_when_over_per_page(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
    monkeypatch,
):
    """Page 1 shows up to `DEFAULT_PAGE_SIZE` rows and a Next link;
    page 2 shows the rest and a Prev link. Monkeypatches the page
    size down to keep the seed cheap — the framework's `handle_list`
    reads the constant from `handlers.DEFAULT_PAGE_SIZE`, so that's
    where the patch lives."""
    monkeypatch.setattr("src.framework.dispatch.handlers.DEFAULT_PAGE_SIZE", 2)
    for _ in range(3):
        await _seed_provider_for(db_test_session_manager, user_id=logged_in_user.id)

    response = await authenticated_client.get("/providers")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#providers-table tbody tr")
    assert len(rows) == 2
    pagination = tree.css_first('nav[aria-label="Pagination"]')
    assert pagination is not None
    assert pagination.css_first('a[rel="next"]') is not None
    assert pagination.css_first('a[rel="prev"]') is None

    response2 = await authenticated_client.get("/providers?page=2")
    assert response2.status_code == 200
    tree2 = HTMLParser(response2.text)
    rows2 = tree2.css("#providers-table tbody tr")
    assert len(rows2) == 1
    pagination2 = tree2.css_first('nav[aria-label="Pagination"]')
    assert pagination2 is not None
    assert pagination2.css_first('a[rel="prev"]') is not None
    assert pagination2.css_first('a[rel="next"]') is None


async def test_list_pagination_preserves_query_params(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
    monkeypatch,
):
    """A page-link from `/providers?foo=bar&page=1` round-trips
    `foo=bar` — the Next link must preserve query state so the user
    doesn't lose their filter when navigating. `base_query()` is
    filter-agnostic: anything in the URL except `page=` carries over,
    so any extra param works as the test signal."""
    monkeypatch.setattr("src.framework.dispatch.handlers.DEFAULT_PAGE_SIZE", 1)
    for _ in range(2):
        await _seed_provider_for(db_test_session_manager, user_id=logged_in_user.id)

    response = await authenticated_client.get("/providers?ignored_param=foo")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    next_link = tree.css_first('nav[aria-label="Pagination"] a[rel="next"]')
    assert next_link is not None
    href = next_link.attributes.get("href", "")
    assert "ignored_param=foo" in href
    assert "page=2" in href
