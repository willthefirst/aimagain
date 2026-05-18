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
    licensure = make_provider_licensure(
        provider_id=provider_id, license_type="lcsw", license_number="L-99999"
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
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                make_provider_licensure(
                    provider_id=provider_id, license_type="lcsw", issuing_state="CA"
                )
            )
            session.add(
                make_provider_licensure(
                    provider_id=provider_id, license_type="lpc", issuing_state="CT"
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


async def test_list_providers_renders_empty_state(
    authenticated_client: AsyncClient,
):
    """With no persisted providers, the page renders a friendly empty
    message instead of an empty `<table>`. The list page's toolbar
    links to `/providers/search`; the multi-select widgets live there,
    not on the list page."""
    response = await authenticated_client.get("/providers")
    assert response.status_code == 200
    assert "No providers found" in response.text
    tree = HTMLParser(response.text)
    assert tree.css_first("#providers-table") is None
    # Filter link goes to the dedicated search page.
    link = tree.css_first("a.toolbar-filter-link")
    assert link is not None
    assert (link.attributes.get("href") or "").startswith("/providers/search")
    # The filter widgets live on the search page — both filters are
    # now multi-select (`<select multiple>`) with no preselected option
    # when no filter is active.
    search_response = await authenticated_client.get("/providers/search")
    assert search_response.status_code == 200
    search_tree = HTMLParser(search_response.text)
    for select_name in ("license_type", "issuing_state"):
        select = search_tree.css_first(f'select[name="{select_name}"][multiple]')
        assert select is not None
        assert not select.css(
            "option[selected]"
        ), f"{select_name} should have no preselected option when filter is inactive"


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

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                make_provider_licensure(provider_id=provider_a, license_type="psyd")
            )
            session.add(
                make_provider_licensure(provider_id=provider_b, license_type="lcsw")
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
    search = await authenticated_client.get("/providers/search?license_type=psyd")
    assert search.status_code == 200
    selected = HTMLParser(search.text).css_first(
        'select[name="license_type"] option[selected]'
    )
    assert selected is not None
    assert selected.attributes.get("value") == "psyd"


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


async def test_providers_list_toolbar_renders_only_filter_link(
    authenticated_client: AsyncClient,
):
    """`/providers` has no list-level action (no Create button), so the
    toolbar renders only the filter link — no action menu."""
    response = await authenticated_client.get("/providers")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("a.toolbar-filter-link") is not None
    assert tree.css_first("menu.toolbar-right") is None


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


async def test_provider_form_new_omits_bottom_back_link(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /providers/form` renders the create form with no redundant
    bottom "Back to providers" link — primary nav is the way back."""
    response = await authenticated_client.get("/providers/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    bottom_back = tree.css_first('a[href="/providers"][role="button"]')
    assert bottom_back is None


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


# --- Provider delete ------------------------------------------------------


async def test_delete_provider_returns_204_and_cascades(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    provider_id = await _seed_provider_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(make_provider_licensure(provider_id=provider_id))
            session.add(make_provider_education(provider_id=provider_id))
            session.add(make_provider_certification(provider_id=provider_id))

    response = await authenticated_client.delete(f"/providers/{provider_id}")
    assert response.status_code == 204

    async with db_test_session_manager() as session:
        assert (
            await session.execute(select(Provider).filter(Provider.id == provider_id))
        ).scalars().first() is None
        # Sub-rows cascade-deleted via FK ON DELETE CASCADE + ORM cascade.
        assert (
            await session.execute(
                select(ProviderLicensure).filter(
                    ProviderLicensure.provider_id == provider_id
                )
            )
        ).scalars().first() is None
        assert (
            await session.execute(
                select(ProviderEducation).filter(
                    ProviderEducation.provider_id == provider_id
                )
            )
        ).scalars().first() is None
        assert (
            await session.execute(
                select(ProviderCertification).filter(
                    ProviderCertification.provider_id == provider_id
                )
            )
        ).scalars().first() is None


# --- Licensure sub-resource ---------------------------------------------


async def test_patch_licensure_updates_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    provider_id = await _seed_provider_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    licensure = make_provider_licensure(provider_id=provider_id, license_number="L-1")
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
    other_licensure = make_provider_licensure(provider_id=other_provider_id)
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
    # Lists every Org in the directory (#524).
    org_select = tree.css_first('select[name="org_id"]')
    assert org_select is not None
    org_options = org_select.css("option")
    assert any(
        o.text(strip=True) == "Seeded Org" for o in org_options
    ), "Org dropdown should include every seeded Organization"
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
    licensure = make_provider_licensure(
        provider_id=provider_id, license_type="lcsw", license_number="L-12345"
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
