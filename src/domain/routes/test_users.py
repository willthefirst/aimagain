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
from tests.helpers import create_test_user, make_clinician_with_org, promote_to_admin

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


# --- Base template nav ---------------------------------------------------


async def test_base_template_renders_primary_nav_when_authenticated(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """Authenticated pages render a primary nav with a brand link on the
    left and a <details>/<summary> collapsible menu containing four
    destination links: Home, Posts, Profile, and Sign out. The <details>
    pattern supports a mobile hamburger toggle at narrow widths while
    keeping all links visible inline on desktop via CSS.

    The "Create clinician" chrome CTA was removed in #697 — the
    /users/me detail page is the discoverable entry point."""
    response = await authenticated_client.get("/users")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    # "Create clinician" button no longer lives in the nav (#697).
    cta_items = tree.css("#primary-nav a[href='/clinicians/form']")
    assert len(cta_items) == 0, "Create-clinician CTA should be removed from nav (#697)"
    # Brand link is a direct child of the nav element.
    assert tree.css_first('#primary-nav > a[href="/"]') is not None
    # Profile link points at /users/me.
    assert tree.css_first('#primary-nav a[href="/users/me"]') is not None
    # The four authed-chrome destinations render in this exact order
    # inside #nav-menu. Sign-out is the `#` placeholder href on the
    # `<a hx-post>` that drives the HTMX POST.
    nav_items = tree.css("#nav-menu ul li a")
    nav_hrefs = [a.attributes.get("href") for a in nav_items]
    assert nav_hrefs == [
        "/home",
        "/posts",
        "/users/me",
        "#",
    ]


async def test_primary_nav_highlights_active_section(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """The Posts tab lights on its own list page and subpaths."""
    posts = await authenticated_client.get("/posts")
    tree = HTMLParser(posts.text)
    assert (
        tree.css_first('nav[aria-label="Primary"] a[href="/posts"]').attributes.get(
            "aria-current"
        )
        == "page"
    )


async def test_base_template_renders_primary_nav_for_anonymous_visitors(
    test_client: AsyncClient,
):
    """The primary nav renders on every screen — public auth-flow pages
    included — so the chrome stays consistent across the auth gate.
    Anonymous visitors see only the brand link; the chrome carries no
    Login shortcut and no profile link (which would 401). Visitors
    enter the auth flow from the landing page CTA.

    The cross-path no-link contract is pinned at the isolation level
    in `test_primary_nav_omits_login_link_for_anonymous_visitors`
    (`src/framework/templates/test_views.py`); this end-to-end test
    just confirms a representative anonymous response renders the
    expected shape."""
    response = await test_client.get("/auth/login")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    nav = tree.css_first('nav[aria-label="Primary"]')
    assert nav is not None
    # Brand link is present.
    brand = nav.css_first('a[href="/"]')
    assert brand is not None
    # No profile link, no Login link, no Login indicator.
    assert tree.css_first('#primary-nav a[href="/users/me"]') is None
    assert tree.css_first('#primary-nav a[href="/auth/login"]') is None
    assert tree.css_first('#primary-nav span[aria-current="page"]') is None


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
    """User detail uses the consolidated chrome: a back affordance that
    links to `/users` (the deepest clickable parent) and a toolbar
    `<h1>` that carries the current user's name. The current item is
    NOT repeated in the breadcrumb — every visible breadcrumb element
    is an actionable link (GOV.UK pattern)."""
    target_username = f"target-{uuid.uuid4()}"
    target = create_test_user(username=target_username)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    back = tree.css_first('nav[aria-label="breadcrumb"] a.breadcrumb-back')
    assert back is not None
    assert back.attributes.get("href") == "/users"
    label = back.css_first("span.breadcrumb-back-label")
    assert label is not None and label.text(strip=True) == "Users"
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
    """Admin actions render inside the page toolbar (not the
    `.entity-card` body). This pins the "primary resource actions live
    in the toolbar" rule documented in `src/framework/templates/README.md`."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")
    tree = HTMLParser(response.text)
    activation_selector = f"button[hx-put='/users/{target.id}/activation']"
    assert tree.css_first(f".toolbar {activation_selector}") is not None
    # Sanity: not duplicated inside the detail-page card body.
    assert tree.css_first(f".entity-card {activation_selector}") is None


async def test_self_detail_renders_favorites_link_in_body_not_toolbar(
    authenticated_client: AsyncClient,
):
    """Favorites is navigation, not an Action — the toolbar is reserved
    for Actions (Sign out, admin Deactivate/Delete). The link to the
    viewer's favorites list lives in the detail-page body."""
    response = await authenticated_client.get("/users/me")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    favorites_selector = "a[href='/users/me/favorites']"
    assert tree.css_first(f".toolbar {favorites_selector}") is None, (
        "Favorites link must not appear in the toolbar — toolbar is for " "Actions only"
    )
    assert (
        tree.css_first(f"main {favorites_selector}") is not None
    ), "Favorites link must appear in the page body for the self viewer"


async def test_other_user_detail_hides_favorites_link(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Viewing someone else's profile must not expose their private
    favorites list — the Favorites body section is self-only."""
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("a[href='/users/me/favorites']") is None


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


async def test_detail_no_inline_clinicians_section(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The inline Clinicians section was removed from the user detail page —
    clinicians are accessible via /users/me/clinicians instead."""
    response = await authenticated_client.get("/users/me")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    headings = [
        el.text(strip=True)
        for el in tree.css("section.entity-card header.entity-header strong")
    ]
    assert "Clinicians" not in headings
    return None


async def test_users_me_access_card_links_to_access_page(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /users/me` shows an Access card with a link to the access overview.
    Capability status is on /users/me/access, not embedded here. Self-only."""
    response = await authenticated_client.get("/users/me")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    headings = [
        el.text(strip=True)
        for el in tree.css("section.entity-card header.entity-header strong")
    ]
    assert "Access" in headings, "/users/me is missing the Access card"
    access_link = tree.css_first("section.entity-card a[href$='/users/me/access']")
    assert (
        access_link is not None
    ), "Access card is missing the link to /users/me/access"
    assert (
        "Network access" not in response.text
    ), "Capability status must not be embedded on /users/me"


async def test_users_me_email_card_links_to_email_form(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /users/me` shows an Email card with a link to /users/me/email/form
    so users can reach the verification resend without going through the
    capability tree. Self-only."""
    response = await authenticated_client.get("/users/me")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    headings = [
        el.text(strip=True)
        for el in tree.css("section.entity-card header.entity-header strong")
    ]
    assert "Email" in headings, "/users/me is missing the Email card"
    email_link = tree.css_first("section.entity-card a[href$='/users/me/email/form']")
    assert (
        email_link is not None
    ), "Email card is missing the link to /users/me/email/form"


async def test_users_me_email_card_not_shown_for_other_users(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The Email card must NOT appear on another user's profile — self-only."""
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    email_link = tree.css_first("section.entity-card a[href$='/email/form']")
    assert email_link is None, "Email card must not appear on another user's profile"


async def test_users_me_verification_card_not_shown_for_other_users(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The 'Verification' status card must NOT appear on other users'
    profile pages — it is self-only."""
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    headings = [
        el.text(strip=True)
        for el in tree.css("section.entity-card header.entity-header strong")
    ]
    assert (
        "Verification" not in headings
    ), "Verification card unexpectedly shown on another user's profile"


async def test_detail_no_inline_clinicians_section_for_other_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Viewing another user's profile has no Clinicians section — it was
    removed entirely from the user detail page."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    headings = [
        el.text(strip=True)
        for el in tree.css("section.entity-card header.entity-header strong")
    ]
    assert "Clinicians" not in headings


# --- Sign out -----------------------------------------------------------


def _signout_button(tree: HTMLParser):
    """Find the Sign out button in the toolbar action menu — keyed off
    `hx-post="/auth/jwt/logout"` rather than text because the button
    label is the only visible signal of the action and the test should
    pin the wire contract (the htmx POST target), not the copy."""
    for button in tree.css("button[hx-post]"):
        if button.attributes.get("hx-post") == "/auth/jwt/logout":
            return button
    return None


async def test_detail_shows_signout_for_self(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`/users/me` exposes a Sign out button in the toolbar action menu
    so a user can end their session from somewhere visible (was
    previously only reachable by knowing the POST /auth/jwt/logout
    endpoint exists). Pin the htmx POST target + the after-request
    redirect hook so the button's wire behavior stays in lockstep."""
    response = await authenticated_client.get("/users/me")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    button = _signout_button(tree)
    assert button is not None, "self profile is missing the Sign out button"
    on_after = button.attributes.get("hx-on::after-request") or ""
    assert "window.location" in on_after, (
        "Sign out button must redirect after the 204 logout response — "
        "fastapi-users' logout returns 204 with no body, so the htmx "
        "swap alone leaves the browser on /users/me."
    )


async def test_detail_omits_signout_for_other_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Viewing another user's profile (including as admin) does NOT
    surface the Sign out button — that affordance is self-only.
    Otherwise an admin could accidentally sign out the user they're
    auditing, which is both confusing and would do nothing useful (the
    admin's own session would also end since cookies are per-browser).
    """
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert _signout_button(tree) is None


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


async def test_primary_nav_marks_profile_active_on_users_me(
    authenticated_client: AsyncClient,
):
    """The Profile link in the primary nav points at `/users/me` and
    carries `aria-current="page"` when the user is on it."""
    response = await authenticated_client.get("/users/me")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    profile_link = tree.css_first('#primary-nav a[href="/users/me"]')
    assert (
        profile_link is not None
        and profile_link.attributes.get("aria-current") == "page"
    ), "expected Profile link to carry aria-current=page on /users/me"


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


# --- Clinicians ownership-subresource ----------------------------


async def _seed_user_clinician(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    practice_name: str,
) -> uuid.UUID:
    clinician = make_clinician_with_org(owner_id=user_id, practice_name=practice_name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
        await session.refresh(clinician)
        return clinician.id


async def test_get_my_clinicians_empty_state(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /users/me/clinicians` renders the empty state when the
    current user owns no clinicians."""
    response = await authenticated_client.get("/users/me/clinicians")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    tree = HTMLParser(response.text)
    assert tree.css_first("#user-clinicians-list") is None
    empty = tree.css_first("#user-clinicians-empty")
    assert empty is not None
    assert "have not created" in empty.text()


def _create_clinician_action(tree: HTMLParser):
    for anchor in tree.css('menu.toolbar-right > li > a[role="button"]'):
        if "Create clinician" in (anchor.text() or ""):
            return anchor
    return None


async def test_get_my_clinicians_shows_create_action_in_toolbar(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Self viewing their own clinician list sees a 'Create clinician'
    toolbar action — present both in the empty state and after the
    user has created one (so they can create additional clinicians)."""
    empty_response = await authenticated_client.get("/users/me/clinicians")
    empty_tree = HTMLParser(empty_response.text)
    empty_action = _create_clinician_action(empty_tree)
    assert empty_action is not None
    assert empty_action.attributes.get("href") == "/clinicians/form"

    await _seed_user_clinician(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="First"
    )

    with_one_response = await authenticated_client.get("/users/me/clinicians")
    with_one_tree = HTMLParser(with_one_response.text)
    assert _create_clinician_action(with_one_tree) is not None


async def test_get_user_clinicians_omits_create_action_for_other_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """An admin viewing another user's clinician list does NOT see the
    self-only 'Create clinician' toolbar action — admins manage their
    own clinicians, not on behalf of others."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}/clinicians")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert _create_clinician_action(tree) is None


async def test_get_user_clinicians_self(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /users/{my_id}/clinicians` works for the current user
    (equivalent to the /me alias)."""
    await _seed_user_clinician(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Mine"
    )

    response = await authenticated_client.get(f"/users/{logged_in_user.id}/clinicians")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert len(tree.css("#user-clinicians-list article.entity-card")) == 1


async def test_get_user_clinicians_admin_can_view_other(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Admin can view another user's clinician list."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)
    await _seed_user_clinician(
        db_test_session_manager, user_id=target.id, practice_name="Target Practice"
    )

    response = await authenticated_client.get(f"/users/{target.id}/clinicians")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert len(tree.css("#user-clinicians-list article.entity-card")) == 1


async def test_get_user_clinicians_non_admin_forbidden_for_other(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A non-admin user cannot view another user's clinician list."""
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}/clinicians")
    assert response.status_code == 403


async def test_get_user_clinicians_404_for_unknown_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Admin requesting an unknown user's list gets 404 (not 403)."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)

    response = await authenticated_client.get(f"/users/{uuid.uuid4()}/clinicians")
    assert response.status_code == 404


async def test_get_my_clinicians_renders_breadcrumb(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /users/me/clinicians` renders a breadcrumb back-affordance
    pointing at the current user's profile — auto-injected by
    `mount_related_list` via `USER_ENTITY.display_label_fn`."""
    response = await authenticated_client.get("/users/me/clinicians")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    back = tree.css_first('nav[aria-label="breadcrumb"] a.breadcrumb-back')
    assert (
        back is not None
    ), "user clinicians list must render a breadcrumb back-affordance"
    assert back.attributes.get("href") == f"/users/{logged_in_user.id}"
    label = back.css_first("span.breadcrumb-back-label")
    assert label is not None and label.text(strip=True) == logged_in_user.username
