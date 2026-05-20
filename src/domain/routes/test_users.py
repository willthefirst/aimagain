import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy import select

# Import session maker type for hinting
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import User
from src.framework.audit.log import AuditLog
from src.framework.audit.repository import AuditRepository
from tests.helpers import create_test_user, make_provider_with_org, promote_to_admin

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


# --- Base template nav ---------------------------------------------------


async def test_base_template_renders_primary_nav_when_authenticated(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """Authenticated pages render the primary nav with the two Journey
    surfaces on the left (Referrals = "find new clients", Openings =
    "refer out a client") and on the right an adaptive primary CTA
    (Create-clinician for first-time users without a provider profile,
    Create-opening for returning users) plus the `/users/me` profile
    icon. Other URL families — `/intakes`, `/clinicians`,
    `/organizations`, `/programs`, `/users` — stay live and reachable
    by URL/bookmark, but are no longer chrome-promoted."""
    response = await authenticated_client.get("/users")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    profile_items = tree.css("#primary-nav > li > a")
    profile_hrefs = {a.attributes.get("href") for a in profile_items}
    # First-time user (no `Provider` row yet) — the CTA points at
    # `/clinicians/form` so they can unblock posting.
    assert profile_hrefs == {"/clinicians/form", "/users/me"}
    section_items = tree.css('nav[aria-label="Primary"] > ul:first-of-type > li > a')
    section_hrefs = [a.attributes.get("href") for a in section_items]
    # Brand link is `<li><strong><a>` so the `> li > a` direct-child
    # selector picks up only the section shortcuts in render order.
    assert section_hrefs == [
        "/referrals",
        "/openings",
    ]


async def test_primary_nav_highlights_active_section(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """The two journey tabs (Referrals / Openings) light on their own
    list page and subpaths; the other tab does not."""
    referrals = await authenticated_client.get("/referrals")
    tree = HTMLParser(referrals.text)
    assert (
        tree.css_first('nav[aria-label="Primary"] a[href="/referrals"]').attributes.get(
            "aria-current"
        )
        == "page"
    )
    assert (
        tree.css_first('nav[aria-label="Primary"] a[href="/openings"]').attributes.get(
            "aria-current"
        )
        is None
    )


async def test_base_template_renders_primary_nav_for_anonymous_visitors(
    test_client: AsyncClient,
):
    """The primary nav renders on every screen — public auth-flow pages
    included — so the chrome stays consistent across the auth gate.
    Anonymous visitors get the brand link plus a Login shortcut on the
    right (no `/users/me` link, which would 401). The `{% if
    is_authenticated %}` branch lives inside `#primary-nav` so the
    nav scaffold is always present and only its right-side item swaps.

    On `/auth/login` itself the Login shortcut is rendered as a
    non-link `<span aria-current="page">` so the chrome doesn't offer a
    self-referential click target (see issue #591); that branch is
    pinned in ``test_primary_nav_suppresses_self_referential_login_link``
    below.
    """
    # Every anonymous-accessible page in production is under
    # `/auth/...`, and the issue-#591 suppression covers all of them,
    # so there is no end-to-end path that exercises the clickable-`<a>`
    # branch — that branch is pinned by the isolation-level unit test
    # in ``src/framework/templates/test_views.py``.
    response = await test_client.get("/auth/login")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    nav = tree.css_first('nav[aria-label="Primary"]')
    assert nav is not None
    # Brand link is present on the left.
    brand = nav.css_first('a[href="/"]')
    assert brand is not None
    # Right-side slot has the Login indicator (rendered as a non-link
    # span on auth-flow pages); no profile link.
    profile_link = tree.css_first('#primary-nav a[href="/users/me"]')
    assert profile_link is None
    # No clickable `<a href="/auth/login">` on the login page itself.
    assert tree.css_first('#primary-nav a[href="/auth/login"]') is None
    # The Login indicator is a `<span aria-current="page">`.
    login_indicator = tree.css_first('#primary-nav span[aria-current="page"]')
    assert login_indicator is not None
    assert login_indicator.text().strip() == "Login"


@pytest.mark.parametrize(
    "path",
    [
        "/auth/login",
        "/auth/register",
        "/auth/forgot-password",
    ],
)
async def test_primary_nav_suppresses_self_referential_login_link(
    test_client: AsyncClient,
    path: str,
):
    """On every anonymous-accessible auth-flow page the top-right
    Login shortcut must not link to `/auth/login` — clicking a header
    link that points where you already are (or to a sibling auth page
    that has the same chrome) is the bug filed in issue #591. The
    suppression covers `/auth/login`, `/auth/register`, and
    `/auth/forgot-password` so the chrome reads consistently across
    the public auth flow."""
    response = await test_client.get(path)
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first('#primary-nav a[href="/auth/login"]') is None
    login_indicator = tree.css_first('#primary-nav span[aria-current="page"]')
    assert (
        login_indicator is not None
    ), f"expected #primary-nav to carry a non-link Login indicator on {path}"
    assert login_indicator.text().strip() == "Login"


# --- Listing -------------------------------------------------------------


async def test_list_users_empty(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """Test GET /users returns HTML with no other users message when only logged in user exists."""
    response = await authenticated_client.get(f"/users")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    assert "No users found" in tree.body.text()
    link_node = tree.css_first(f'a[href*="/users"]')
    assert link_node is not None, "Refresh link not found"


async def test_list_users_multiple_users(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test GET /users returns HTML listing multiple other users."""
    user1 = create_test_user(username=f"test-user-one-{uuid.uuid4()}")
    user2 = create_test_user(username=f"test-user-two-{uuid.uuid4()}")

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([user1, user2])

    response = await authenticated_client.get(f"/users")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    user_list_items = tree.css("#user-list article.entity-card")
    assert len(user_list_items) == 2, "Expected two users in the list"

    usernames_found = {item.text() for item in user_list_items}
    assert any(
        user1.username in u for u in usernames_found
    ), f"{user1.username} not found in list"
    assert any(
        user2.username in u for u in usernames_found
    ), f"{user2.username} not found in list"
    assert all(
        logged_in_user.username not in u for u in usernames_found
    ), "Logged in user should not be listed"
    assert "No users found" not in tree.body.text()


# --- Admin actions partial visibility ------------------------------------


async def test_list_hides_admin_actions_for_non_admin(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Non-admin viewers must not see deactivate/delete buttons."""
    other = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)

    response = await authenticated_client.get("/users")
    tree = HTMLParser(response.text)
    assert (
        tree.css_first("button[hx-put*='/activation']") is None
    ), "Non-admin should not see admin action buttons"


async def test_list_shows_admin_actions_for_admin(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Admin viewers see deactivate + delete buttons on each non-self row."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)

    response = await authenticated_client.get("/users")
    tree = HTMLParser(response.text)
    activation_buttons = tree.css(f"button[hx-put='/users/{other.id}/activation']")
    assert (
        len(activation_buttons) == 1
    ), "Expected one activation button (one non-self row)"
    assert activation_buttons[0].text().strip() == "Deactivate"
    assert tree.css_first(f"button[hx-delete='/users/{other.id}']") is not None


async def test_list_shows_reactivate_for_deactivated_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A deactivated user shows 'Reactivate' rather than 'Deactivate'."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"target-{uuid.uuid4()}", is_active=False)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)

    response = await authenticated_client.get("/users")
    tree = HTMLParser(response.text)
    activation_button = tree.css_first(f"button[hx-put='/users/{other.id}/activation']")
    assert activation_button is not None
    assert activation_button.text().strip() == "Reactivate"


# --- Detail page ---------------------------------------------------------


async def test_get_user_detail_renders(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """GET /users/{id} renders the detail page for an existing user."""
    target_username = f"target-{uuid.uuid4()}"
    target = create_test_user(username=target_username)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert target_username in tree.body.text()


async def test_get_user_detail_renders_breadcrumb_and_heading(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """User detail uses the consolidated chrome: a one-segment
    breadcrumb that links back to `/users` and a toolbar `<h1>` that
    carries the current user's name. The current item is NOT
    repeated as a non-link crumb — every visible breadcrumb item is
    an actionable link (GOV.UK pattern)."""
    target_username = f"target-{uuid.uuid4()}"
    target = create_test_user(username=target_username)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    items = tree.css('nav[aria-label="breadcrumb"] ul > li')
    assert [li.text(strip=True) for li in items] == ["Users"]
    parent = items[0].css_first("a")
    assert parent is not None
    assert parent.attributes.get("href") == "/users"
    # Current item lives in the toolbar <h1>, not the breadcrumb.
    h1 = tree.css_first("div.toolbar h1")
    assert h1 is not None
    assert h1.text(strip=True) == target_username


async def test_detail_hides_private_fields_from_strangers(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A non-admin viewer looking at *someone else's* profile must not
    see email, is_active, or is_verified — those are private to the
    user themselves and admins. The handler's projection omits the
    fields entirely from context, so even the values can't leak via
    a forgotten template guard."""
    target_email = f"private-{uuid.uuid4()}@example.com"
    target = create_test_user(
        username=f"target-{uuid.uuid4()}",
        email=target_email,
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")

    assert response.status_code == 200
    body = response.text
    assert target_email not in body
    # The labels themselves are gated, not just the values — no
    # `<dt>Email</dt>` row should render at all.
    assert "<dt>Email</dt>" not in body
    assert "<dt>Active</dt>" not in body
    assert "<dt>Verified</dt>" not in body


async def test_detail_shows_email_but_hides_admin_fields_for_self(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """The user viewing their own profile (via /users/me or
    /users/<own-id>) sees their email but NOT the Active or Verified
    rows — those are admin signals (#597). Admins viewing someone
    else still see all three (see
    ``test_detail_shows_private_fields_to_admin``)."""
    response = await authenticated_client.get("/users/me")

    assert response.status_code == 200
    body = response.text
    assert logged_in_user.email in body
    assert "<dt>Email</dt>" in body
    assert "<dt>Active</dt>" not in body
    assert "<dt>Verified</dt>" not in body


async def test_detail_shows_private_fields_to_admin(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """An admin viewing any user's profile sees the private fields."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target_email = f"target-{uuid.uuid4()}@example.com"
    target = create_test_user(
        username=f"target-{uuid.uuid4()}",
        email=target_email,
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")

    assert response.status_code == 200
    body = response.text
    assert target_email in body
    assert "<dt>Email</dt>" in body


async def test_detail_shows_admin_actions_for_admin(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Admin viewing another user's detail page sees the actions partial."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")
    tree = HTMLParser(response.text)
    assert tree.css_first(f"button[hx-put='/users/{target.id}/activation']") is not None


async def test_detail_admin_actions_render_inside_toolbar(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Admin actions render inside the page toolbar (not the `<article>`
    body). This pins the "primary resource actions live in the toolbar"
    rule documented in `src/framework/templates/README.md`."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")
    tree = HTMLParser(response.text)
    activation_selector = f"button[hx-put='/users/{target.id}/activation']"
    assert tree.css_first(f".toolbar {activation_selector}") is not None
    # Sanity: not duplicated inside <article>.
    assert tree.css_first(f"article {activation_selector}") is None


async def test_detail_hides_admin_actions_for_non_admin(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Non-admin viewing another user's detail page does not see actions."""
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")
    tree = HTMLParser(response.text)
    assert tree.css_first(f"button[hx-put='/users/{target.id}/activation']") is None


async def test_detail_shows_providers_empty_state(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """User with no providers → empty-state copy on the detail page."""
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("#user-detail-clinicians") is None
    empty = tree.css_first("#user-detail-clinicians-empty")
    assert empty is not None
    assert "No clinician entries yet" in empty.text()


async def test_detail_lists_owned_providers(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """User with multiple providers → all are linked from the detail page."""
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)
    first = make_provider_with_org(owner_id=target.id, practice_name="First")
    second = make_provider_with_org(owner_id=target.id, practice_name="Second")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([first, second])
        await session.refresh(first)
        await session.refresh(second)

    response = await authenticated_client.get(f"/users/{target.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("#user-detail-clinicians-empty") is None
    rows = tree.css("#user-detail-clinicians article.entity-card")
    assert len(rows) == 2
    # After #642 PR 3 the Practice cell anchors to the owning Org per
    # affiliation (each Provider here has its own auto-built Org via
    # `make_provider_with_org`). The Provider id rides on the row's
    # `data-row-id`; assert both Providers surface via that attribute.
    row_ids = {row.attributes.get("data-row-id") for row in rows}
    assert row_ids == {str(first.id), str(second.id)}


def _inline_create_provider_link(tree: HTMLParser):
    """The detail page's Providers card renders the self-only Create
    CTA as `<a role="button">Create clinician</a>` inside the
    `.entity-card`'s `<footer>`. Distinct from the toolbar variant on
    `/users/{id}/clinicians` — this one is the profile inline preview."""
    for anchor in tree.css(".entity-card a[role='button']"):
        if "Create clinician" in (anchor.text() or ""):
            return anchor
    return None


async def test_detail_shows_inline_create_provider_for_self(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`/users/me` (and `/users/{my_id}`) renders an inline 'Create
    provider' button inside the Providers section so the profile is
    a self-discovery entry point — without the user clicking through
    to the dedicated `/users/me/clinicians` page."""
    response = await authenticated_client.get("/users/me")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    action = _inline_create_provider_link(tree)
    assert action is not None, "self profile is missing inline Create clinician link"
    assert action.attributes.get("href") == "/clinicians/form"


async def test_detail_omits_inline_create_provider_for_other_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Viewing another user's profile (including as admin) does NOT
    surface the Create clinician CTA — that affordance is self-only,
    mirroring the toolbar variant on `/users/{id}/clinicians`."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert _inline_create_provider_link(tree) is None


# --- Chrome: font preload (icon-flicker fix) ----------------------------


async def test_base_template_preloads_lucide_icon_font(
    authenticated_client: AsyncClient,
):
    """``base.html`` emits a `<link rel="preload">` for the Lucide
    woff2 font ahead of the stylesheet `<link>` so the icon font
    fetch runs in parallel with the CSS fetch rather than waiting for
    it to parse. This eliminates the icon-flicker that's otherwise
    visible on every first paint while ``<i class="icon-x">`` elements
    render as blank space waiting for the font.

    Pin the contract: the preload URL MUST match the CSS's woff2 URL
    *exactly* (including the cache-buster query) or the browser sees
    them as different resources and the preload is wasted."""
    response = await authenticated_client.get("/users/me")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    preload = tree.css_first('link[rel="preload"][as="font"]')
    assert preload is not None, "Lucide woff2 preload <link> is missing"
    href = preload.attributes.get("href") or ""
    assert "lucide.woff2" in href
    assert preload.attributes.get("type") == "font/woff2"
    # Required for cross-origin font preloads — without it, the
    # browser fetches the font twice (once preload, once for real).
    assert "crossorigin" in preload.attributes
    # The companion stylesheet `<link>` references the same font URL
    # via its `@font-face` rule; the preload's href must include the
    # CSS's cache-buster so the browser deduplicates the requests.
    assert "?t=" in href, (
        "preload href must include the lucide.css cache-buster query "
        "(`?t=...`); without exact-URL match the browser issues a "
        "second font request and the preload is wasted"
    )


# --- Chrome: nav active state -------------------------------------------


async def test_primary_nav_marks_profile_active_on_users_me_subpaths(
    authenticated_client: AsyncClient,
):
    """The profile icon links to `/users/me` and shows `aria-current`
    on any `/users/me/*` path — `/users/me/favorites` is the canonical
    case but the rule covers every nested profile sub-route."""
    response = await authenticated_client.get("/users/me/favorites")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    profile_link = tree.css_first('#primary-nav a[href="/users/me"]')
    assert profile_link.attributes.get("aria-current") == "page"


# --- Activation endpoint -------------------------------------------------


async def test_admin_can_deactivate_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}", is_active=True)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.put(
        f"/users/{target.id}/activation",
        json={"state": "deactivated"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_active"] is False
    assert response.headers.get("HX-Refresh") == "true"

    # Confirm persisted
    async with db_test_session_manager() as session:
        result = await session.execute(select(User).filter(User.id == target.id))
        refreshed = result.scalars().first()
        assert refreshed.is_active is False


async def test_admin_can_reactivate_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}", is_active=False)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.put(
        f"/users/{target.id}/activation",
        json={"state": "active"},
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is True


async def test_non_admin_cannot_deactivate_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Non-admin gets 403 even with a valid body — backend enforces authz, not just templates."""
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.put(
        f"/users/{target.id}/activation",
        json={"state": "deactivated"},
    )
    assert response.status_code == 403


async def test_admin_cannot_deactivate_self(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Self-guard: admin acting on their own id is rejected at the logic layer."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)

    response = await authenticated_client.put(
        f"/users/{logged_in_user.id}/activation",
        json={"state": "deactivated"},
    )
    assert response.status_code == 403


async def test_activation_404_for_unknown_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    response = await authenticated_client.put(
        f"/users/{uuid.uuid4()}/activation",
        json={"state": "deactivated"},
    )
    assert response.status_code == 404


# --- Delete endpoint -----------------------------------------------------


async def test_admin_can_delete_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.delete(f"/users/{target.id}")
    assert response.status_code == 204
    assert response.headers.get("HX-Redirect") == "/users"

    async with db_test_session_manager() as session:
        result = await session.execute(select(User).filter(User.id == target.id))
        assert result.scalars().first() is None


async def test_admin_cannot_delete_self(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    response = await authenticated_client.delete(f"/users/{logged_in_user.id}")
    assert response.status_code == 403


# --- Audit log -----------------------------------------------------------


async def test_set_user_activation_writes_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Each successful PUT /users/{id}/activation writes one audit row
    capturing before/after activation state, with the admin as actor."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}", is_active=True)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.put(
        f"/users/{target.id}/activation",
        json={"state": "deactivated"},
    )
    assert response.status_code == 200

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="user", resource_id=target.id)
        assert len(rows) == 1
        row = rows[0]
        assert row.actor_id == logged_in_user.id
        assert row.action == "set_user_activation"
        assert row.before == {"is_active": True}
        assert row.after == {"is_active": False}


async def test_failed_activation_writes_no_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A 403 (admin self-guard) leaves no audit trail."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)

    response = await authenticated_client.put(
        f"/users/{logged_in_user.id}/activation",
        json={"state": "deactivated"},
    )
    assert response.status_code == 403

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(
            resource_type="user", resource_id=logged_in_user.id
        )
        assert rows == []


async def test_delete_user_writes_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Each successful DELETE /users/{id} writes one audit row capturing
    the user's pre-delete state in `before`, with `after=None`."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target_username = f"target-{uuid.uuid4()}"
    target = create_test_user(
        username=target_username, is_active=True, is_superuser=False
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)
    target_id = target.id
    target_email = target.email

    response = await authenticated_client.delete(f"/users/{target_id}")
    assert response.status_code == 204

    async with db_test_session_manager() as session:
        # User row gone
        result = await session.execute(select(User).filter(User.id == target_id))
        assert result.scalars().first() is None

        # Audit row preserved with the admin as actor
        result = await session.execute(
            select(AuditLog).filter(
                AuditLog.resource_type == "user",
                AuditLog.resource_id == target_id,
            )
        )
        rows = result.scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.actor_id == logged_in_user.id
        assert row.action == "delete_user"
        assert row.before == {
            "username": target_username,
            "email": target_email,
            "is_active": True,
            "is_superuser": False,
        }
        assert row.after is None


# --- Providers ownership-subresource ----------------------------


async def _seed_user_provider(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    practice_name: str,
) -> uuid.UUID:
    provider = make_provider_with_org(owner_id=user_id, practice_name=practice_name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)
        await session.refresh(provider)
        return provider.id


async def test_get_my_providers_empty_state(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /users/me/clinicians` renders the empty state when the
    current user owns no providers."""
    response = await authenticated_client.get("/users/me/clinicians")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    tree = HTMLParser(response.text)
    assert tree.css_first("#user-clinicians-list") is None
    empty = tree.css_first("#user-clinicians-empty")
    assert empty is not None
    assert "have not created" in empty.text()


def _create_provider_action(tree: HTMLParser):
    for anchor in tree.css('menu.toolbar-right > li > a[role="button"]'):
        if "Create clinician" in (anchor.text() or ""):
            return anchor
    return None


async def test_get_my_providers_shows_create_action_in_toolbar(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Self viewing their own provider list sees a 'Create clinician'
    toolbar action — present both in the empty state and after the
    user has created one (so they can create additional providers)."""
    empty_response = await authenticated_client.get("/users/me/clinicians")
    empty_tree = HTMLParser(empty_response.text)
    empty_action = _create_provider_action(empty_tree)
    assert empty_action is not None
    assert empty_action.attributes.get("href") == "/clinicians/form"

    await _seed_user_provider(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="First"
    )

    with_one_response = await authenticated_client.get("/users/me/clinicians")
    with_one_tree = HTMLParser(with_one_response.text)
    assert _create_provider_action(with_one_tree) is not None


async def test_get_user_providers_omits_create_action_for_other_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """An admin viewing another user's provider list does NOT see the
    self-only 'Create clinician' toolbar action — admins manage their
    own providers, not on behalf of others."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}/clinicians")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert _create_provider_action(tree) is None


async def test_get_user_providers_self(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /users/{my_id}/clinicians` works for the current user
    (equivalent to the /me alias)."""
    await _seed_user_provider(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Mine"
    )

    response = await authenticated_client.get(f"/users/{logged_in_user.id}/clinicians")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert len(tree.css("#user-clinicians-list article.entity-card")) == 1


async def test_get_user_providers_admin_can_view_other(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Admin can view another user's provider list."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)
    await _seed_user_provider(
        db_test_session_manager, user_id=target.id, practice_name="Target Practice"
    )

    response = await authenticated_client.get(f"/users/{target.id}/clinicians")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert len(tree.css("#user-clinicians-list article.entity-card")) == 1


async def test_get_user_providers_non_admin_forbidden_for_other(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A non-admin user cannot view another user's provider list."""
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}/clinicians")
    assert response.status_code == 403


async def test_get_user_providers_404_for_unknown_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Admin requesting an unknown user's list gets 404 (not 403)."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)

    response = await authenticated_client.get(f"/users/{uuid.uuid4()}/clinicians")
    assert response.status_code == 404


async def test_legacy_provider_paths_gone(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """The legacy `/provider-profiles*` paths were renamed to `/providers*`
    in an earlier PR; #642 PR 4 then flipped `/providers*` →
    `/clinicians*` (no redirects — the design comment on issue #642
    explicitly accepted bookmark breakage). Requests to either old URL
    family — top-level, /me alias, or user-scoped — no longer match
    any route."""
    for path in (
        "/provider-profiles",
        "/users/me/provider-profiles",
        f"/users/{logged_in_user.id}/provider-profiles",
        "/providers",
        "/users/me/providers",
        f"/users/{logged_in_user.id}/providers",
    ):
        response = await authenticated_client.get(path)
        assert response.status_code == 404, f"{path} unexpectedly matched"
