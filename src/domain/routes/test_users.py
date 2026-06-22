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
from tests.helpers import (
    create_test_user,
    make_clinician_with_org,
    make_organization_row,
    promote_to_admin,
)

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


# --- Base template nav ---------------------------------------------------
#
# The authenticated /users/me chrome (primary nav structure, profile-link
# active state, lucide font preload, header sign-out affordance) is pinned
# alongside the detail-page assertions in
# `test_get_users_me_renders_authenticated_self_view` below — every
# previously-separate test for those bits hit the same endpoint with the
# same fixtures, so they share one render.


async def test_primary_nav_highlights_active_section(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """The avatar menu's "My posts" entry lights on the posts list page and
    its subpaths (it is the Posts-family link; the brand `a[href="/posts"]`
    is not section-highlighted)."""
    posts = await authenticated_client.get("/posts")
    tree = HTMLParser(posts.text)
    assert (
        tree.css_first(
            'nav[aria-label="Primary"] a[href="/posts?owner=me"]'
        ).attributes.get("aria-current")
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
    # Brand link is present and points at /home.
    brand = nav.css_first('a[href="/home"]')
    assert brand is not None
    # No profile link, no Login link, no Login indicator.
    assert tree.css_first('nav[aria-label="Primary"] a[href="/users/me"]') is None
    assert tree.css_first('nav[aria-label="Primary"] a[href="/auth/login"]') is None
    assert tree.css_first('nav[aria-label="Primary"] span[aria-current="page"]') is None


# --- Listing -------------------------------------------------------------


async def test_list_users_non_admin_sees_only_self(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The privacy boundary: a non-admin viewer on `/users` sees exactly
    their own row — every other user's username (and existence) is
    filtered out at the repo, not redacted in the template. Enforced by
    `UserRepository.list_users`."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)

    response = await authenticated_client.get("/users")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    items = tree.css("#user-list article")
    assert len(items) == 1, "Non-admin viewer must see exactly their own row"
    text = items[0].text()
    assert logged_in_user.username in text
    assert other.username not in tree.body.text()


async def test_list_users_admin_sees_all_users_including_self(
    superuser_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    superuser_logged_in_user: User,
):
    """Superusers see every user row, including their own — the
    administrative view. The non-admin filter in `UserRepository.list_users`
    is bypassed for superusers."""
    user1 = create_test_user(username=f"test-user-one-{uuid.uuid4()}")
    user2 = create_test_user(username=f"test-user-two-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([user1, user2])

    response = await superuser_client.get("/users")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    body_text = tree.body.text()
    assert user1.username in body_text
    assert user2.username in body_text
    assert superuser_logged_in_user.username in body_text


async def test_list_users_empty_when_solo_admin(
    superuser_client: AsyncClient,
    superuser_logged_in_user: User,
):
    """A superuser viewing `/users` with no other rows present sees
    exactly themselves — not the empty-state message. The empty state
    only renders when the filter genuinely yields zero rows (which can
    no longer happen for an authenticated viewer, since they at minimum
    see themselves)."""
    response = await superuser_client.get("/users")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert "No users found" not in tree.body.text()
    assert superuser_logged_in_user.username in tree.body.text()


# --- Admin actions partial visibility ------------------------------------


async def test_list_omits_admin_actions_for_non_admin(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Non-admin viewers must not see deactivate/delete buttons on the list."""
    other = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)

    response = await authenticated_client.get("/users")
    tree = HTMLParser(response.text)
    assert (
        tree.css_first("button[hx-put*='/activation']") is None
    ), "Non-admin should not see admin action buttons"
    assert (
        tree.css_first("button[hx-delete*='/users/']") is None
    ), "Non-admin should not see admin delete buttons"


async def test_list_omits_admin_actions_for_admin(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Admin viewers do NOT see admin actions on the user list either.

    Per-row admin actions on a card list invite mis-clicks (especially
    the irreversible Delete); admins click through to a user's detail
    page to act. The detail-page toolbar is the canonical home —
    covered by ``test_get_users_id_renders_admin_view_of_other_user``
    below (which pins both that the activation button is present and
    that it lives inside ``.toolbar``).
    """
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)

    response = await authenticated_client.get("/users")
    tree = HTMLParser(response.text)
    assert (
        tree.css_first(f"button[hx-put='/users/{other.id}/activation']") is None
    ), "Admin should not see per-row activation buttons on the list"
    assert (
        tree.css_first(f"button[hx-delete='/users/{other.id}']") is None
    ), "Admin should not see per-row delete buttons on the list"


# --- Detail page ---------------------------------------------------------


def _signout_button(tree: HTMLParser):
    """Find the Sign out button in the toolbar action menu — keyed off
    `hx-post="/auth/jwt/logout"` rather than text because the button
    label is the only visible signal of the action and the test should
    pin the wire contract (the htmx POST target), not the copy."""
    for button in tree.css("button[hx-post]"):
        if button.attributes.get("hx-post") == "/auth/jwt/logout":
            return button
    return None


async def test_get_users_me_renders_authenticated_self_view(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /users/me` for the signed-in user renders the canonical
    account-hub self-view (#1522): the primary nav with brand + the
    `+ Post` button + the avatar menu's My posts/Account/Sign-out
    destinations (Account marked aria-current on this path),
    the lucide font preload <link> for icon-flicker prevention, a
    Sign-out button in the toolbar action menu (htmx POST to
    /auth/jwt/logout with after-request redirect), a body-level
    Favorites link (not in the toolbar), inline Clinicians +
    Organizations lists (each with a `+ Add` CTA and a per-row Edit
    link), and a secondary Account picker with the self-only
    Email/Favorites/Access cards. The page hides top-level identity
    facts (Email/Active/Verified dt entries live on the admin path or
    the Email card; #597).

    Consolidates 10 previously-separate tests that all rendered this
    same response with the same fixtures (one in `test_auth_routes.py`,
    nine here). Distinct assertion messages preserve the per-bit signal
    on failure."""
    # Seed one owned clinician + one owned organization so the inline
    # account-hub lists render rows (not just their empty states).
    clinician_id = await _seed_user_clinician(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="My Practice"
    )
    org_id = await _seed_user_organization(
        db_test_session_manager, user_id=logged_in_user.id, name="My Org"
    )
    response = await authenticated_client.get("/users/me")
    assert response.status_code == 200
    body = response.text
    tree = HTMLParser(body)

    # --- Primary nav structure (canonical Pico nav: brand <ul> + actions <ul>) ---
    # Create-clinician CTA was removed from nav in #697.
    assert (
        tree.css("nav[aria-label='Primary'] a[href='/clinicians/form']") == []
    ), "Create-clinician CTA must be removed from nav (#697)"
    # Brand → posts collection for an authenticated viewer (Browse is the
    # default landing surface); anonymous keeps brand → /home (test_users.py
    # anonymous nav test).
    assert (
        tree.css_first('nav[aria-label="Primary"] a[href="/posts"] strong') is not None
    ), "brand link must point at /posts when authenticated"
    # `Post` link (a visible <li>, outside the profile dropdown) → create form.
    posts = [
        a
        for a in tree.css('nav[aria-label="Primary"] a[href="/posts/form"]')
        if a.text(strip=True) == "Post"
    ]
    assert len(posts) == 1, "`Post` link missing in primary nav"
    # The avatar `<details>` menu carries the non-Post destinations.
    nav_hrefs = [a.attributes.get("href") for a in tree.css("#nav-menu ul li a")]
    assert nav_hrefs == [
        "/posts?owner=me",
        "/users/me",
        "#",
    ], f"nav-menu hrefs unexpected: {nav_hrefs}"

    # --- Account link carries aria-current on this path
    # (was test_primary_nav_marks_profile_active_on_users_me)
    account_link = tree.css_first('#nav-menu a[href="/users/me"]')
    assert (
        account_link is not None
        and account_link.attributes.get("aria-current") == "page"
    ), "Account link must carry aria-current=page on /users/me"

    # --- Every authenticated page exposes the header sign-out link
    # (was test_authenticated_page_has_sign_out_affordance in
    # test_auth_routes.py; that test also hit /users/me, so consolidated
    # here. Header `<a hx-post="/auth/sign-out">` is distinct from the
    # toolbar `<button hx-post="/auth/jwt/logout">` asserted below.)
    assert (
        'hx-post="/auth/sign-out"' in body
    ), "every authenticated page must surface /auth/sign-out in the header chrome"

    # --- Lucide font preload (was test_base_template_preloads_lucide_icon_font)
    # The preload URL MUST match the CSS's `@font-face src` URL exactly
    # — browsers match preloads to actual requests by exact URL. Today
    # both omit a query string; cache-busting on Lucide-version bumps
    # comes from replacing the vendored woff2 bytes (the URL stays
    # the same, ETag changes).
    preload = tree.css_first('link[rel="preload"][as="font"]')
    assert preload is not None, "Lucide woff2 preload <link> is missing"
    href = preload.attributes.get("href") or ""
    assert "lucide.woff2" in href, "preload href must reference lucide.woff2"
    assert preload.attributes.get("type") == "font/woff2"
    # `crossorigin` is required even for same-origin font preloads —
    # browsers fetch fonts in CORS-anonymous mode and a preload that
    # omits the attribute hits the cache under a different key.
    assert "crossorigin" in preload.attributes, "preload <link> missing crossorigin"
    # Self-hosted; the upstream-CDN `?t=...` cache-buster is no longer
    # part of the URL (a same-origin static mount's ETag handles
    # revalidation, see `StaticLongCacheMiddleware`).
    assert href.startswith("/static/fw/fonts/lucide.woff2"), (
        "preload must point at the same-origin self-hosted woff2 mount "
        f"(got {href!r}); the upstream-CDN path was retired alongside "
        "the unused-CSS pruning, see `base.html`."
    )

    # --- Identity facts hidden on self-view
    # (was test_detail_hides_identity_facts_for_self; #597)
    assert "<dt>Email</dt>" not in body, "self-view must not surface Email dt"
    assert "<dt>Active</dt>" not in body, "self-view must not surface Active dt"
    assert "<dt>Verified</dt>" not in body, "self-view must not surface Verified dt"

    # --- Sign-out button in toolbar (was test_detail_shows_signout_for_self)
    # The htmx POST target + after-request redirect must stay in lockstep —
    # fastapi-users' logout returns 204 with no body, so the htmx swap
    # alone leaves the browser on /users/me.
    button = _signout_button(tree)
    assert button is not None, "self profile is missing the Sign out button"
    on_after = button.attributes.get("hx-on::after-request") or ""
    assert (
        "window.location" in on_after
    ), "Sign out button must redirect after the 204 logout response"

    # --- Favorites link in body, not toolbar
    # (was test_self_detail_renders_favorites_link_in_body_not_toolbar)
    favorites_selector = "a[href='/users/me/favorites']"
    assert (
        tree.css_first(f".toolbar {favorites_selector}") is None
    ), "Favorites link must not appear in the toolbar — toolbar is for Actions only"
    assert (
        tree.css_first(f"main {favorites_selector}") is not None
    ), "Favorites link must appear in the page body for the self viewer"

    # --- Inline account-hub lists: Clinicians + Organizations (#1522).
    # The pre-#1522 dispatching picker cards are replaced by inline
    # lists rendered from the owner's own clinicians/organizations.
    section_headings = [el.text(strip=True) for el in tree.css("main section > * h2")]
    assert "Clinicians" in section_headings, "account hub missing Clinicians section"
    assert (
        "Organizations" in section_headings
    ), "account hub missing Organizations section"

    # Each list renders the owner's seeded row through the shared card
    # (selected by data-row-id so it survives card-internal markup
    # changes).
    assert (
        tree.css_first(
            f"#account-clinicians-list article[data-row-id='{clinician_id}']"
        )
        is not None
    ), "owned clinician must render as an inline card in the account hub"
    assert (
        tree.css_first(f"#account-organizations-list article[data-row-id='{org_id}']")
        is not None
    ), "owned organization must render as an inline card in the account hub"

    # Add CTAs point at the global create forms.
    assert (
        tree.css_first("#account-clinicians a[role='button'][href='/clinicians/form']")
        is not None
    ), "Clinicians section missing the + Add clinician CTA -> /clinicians/form"
    assert (
        tree.css_first(
            "#account-organizations a[role='button'][href='/organizations/form']"
        )
        is not None
    ), "Organizations section missing the + Add organization CTA -> /organizations/form"

    # Per-row Edit links point at the row's own edit form.
    assert (
        tree.css_first(
            f"#account-clinicians-list a[href='/clinicians/{clinician_id}/form']"
        )
        is not None
    ), "clinician row missing per-row Edit link -> /clinicians/:id/form"
    assert (
        tree.css_first(
            f"#account-organizations-list a[href='/organizations/{org_id}/form']"
        )
        is not None
    ), "organization row missing per-row Edit link -> /organizations/:id/form"

    # --- Secondary Account picker retains Email / Favorites / Access ---
    headings = [el.text(strip=True) for el in tree.css(".picker-option h2")]

    # Access card (was test_users_me_access_card_links_to_access_page)
    assert "Access" in headings, "/users/me is missing the Access card"
    assert (
        tree.css_first("article.picker-option a[href$='/users/me/access']") is not None
    ), "Access card is missing the link to /users/me/access"
    assert (
        "Network access" not in body
    ), "capability status must not be embedded on /users/me — lives on /users/me/access"

    # Email card (was test_users_me_email_card_links_to_email_form)
    assert "Email" in headings, "/users/me is missing the Email card"
    assert (
        tree.css_first("article.picker-option a[href$='/users/me/email/form']")
        is not None
    ), "Email card is missing the link to /users/me/email/form"


async def test_get_users_id_renders_admin_view_of_other_user(
    superuser_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`GET /users/{target_id}` for an admin viewing another user renders
    the canonical admin view: breadcrumb back to /users, target's
    username un-redacted in the toolbar <h1>, private fields visible
    (Email dt + the email value itself), admin activation actions
    inside the toolbar (single instance, not duplicated), and the
    self-only affordances suppressed: no Sign-out button, no Email
    card (which links to /users/me — self-only), no Verification card,
    no inline Clinicians section (removed entirely from user detail).

    Consolidates 9 previously-separate tests that hit this same endpoint
    with two admin-acquisition shapes (some used `superuser_client`
    directly, others used `authenticated_client` +
    `promote_to_admin(logged_in_user)`). Both shapes produce equivalent
    admin sessions; `superuser_client` is the cleaner one."""
    target_email = f"target-{uuid.uuid4()}@example.com"
    target_username = f"target-{uuid.uuid4()}"
    target = create_test_user(username=target_username, email=target_email)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await superuser_client.get(f"/users/{target.id}")
    assert response.status_code == 200
    body = response.text
    tree = HTMLParser(body)

    # --- Breadcrumb + heading (was test_admin_detail_renders_breadcrumb_and_heading)
    back = tree.css_first('nav[aria-label="breadcrumb"] a.breadcrumb-back')
    assert back is not None, "breadcrumb back-link missing"
    label = back.css_first("span.breadcrumb-back-label")
    assert (
        label is not None and label.text(strip=True) == "Users"
    ), "breadcrumb label must say 'Users'"
    assert (
        back.attributes.get("href") == "/users"
    ), "breadcrumb href must point at /users"
    assert (
        "data-locked-cta" not in back.attributes
    ), "breadcrumb back-link must not be locked"
    h1 = tree.css_first("div.toolbar h1")
    assert h1 is not None and target_username in h1.text(
        strip=True
    ), "toolbar h1 missing target username"
    # Body renders the target's username unredacted
    # (was test_get_user_detail_renders)
    assert (
        target_username in tree.body.text()
    ), "target username must render unredacted in the body"

    # --- Private fields visible to admin
    # (was test_detail_shows_private_fields_to_admin)
    assert target_email in body, "admin should see target's email value"
    assert "<dt>Email</dt>" in body, "admin should see Email dt entry"

    # --- Admin activation action present, inside toolbar, not duplicated
    # (was test_detail_shows_admin_actions_for_admin +
    # test_detail_admin_actions_render_inside_toolbar; pins the
    # "primary resource actions live in the toolbar" rule documented in
    # src/framework/templates/README.md)
    activation_selector = f"button[hx-put='/users/{target.id}/activation']"
    assert (
        tree.css_first(activation_selector) is not None
    ), "admin missing activation button"
    assert (
        tree.css_first(f".toolbar {activation_selector}") is not None
    ), "activation button must live inside .toolbar"
    assert (
        len(tree.css(activation_selector)) == 1
    ), "activation button must render exactly once"

    # --- Self-only affordances suppressed on other-user view ---
    # Sign-out (was test_detail_omits_signout_for_other_user) — admin
    # accidentally signing out the target is confusing, and would only
    # nuke the admin's own session anyway (cookies are per-browser).
    assert (
        _signout_button(tree) is None
    ), "Sign out button must NOT appear when viewing another user"

    # Email card (was test_users_me_email_card_not_shown_for_other_users)
    # — it links to /users/me/email/form, which is self-only.
    assert (
        tree.css_first("article.picker-option a[href$='/email/form']") is None
    ), "Email card must not appear on another user's profile"

    # Verification card
    # (was test_users_me_verification_card_not_shown_for_other_users)
    headings = [el.text(strip=True) for el in tree.css(".picker-option h2")]
    assert (
        "Verification" not in headings
    ), "Verification card must not appear on another user's profile"

    # Inline account-hub sections (#1522) are self-only — an admin
    # auditing another user sees neither the inline Clinicians nor the
    # inline Organizations list, and no Add CTAs.
    assert (
        tree.css_first("#account-clinicians") is None
    ), "no inline Clinicians section on another user's profile"
    assert (
        tree.css_first("#account-organizations") is None
    ), "no inline Organizations section on another user's profile"
    # The global onboarding banner (#1525) is chrome — it links to the create
    # forms for the *viewing* user's own incomplete setup and legitimately
    # appears site-wide. Strip it before asserting the self-only account-hub
    # Add CTAs (the inline sections above) don't leak onto another user's page.
    for _banner in tree.css("#onboarding-banner"):
        _banner.decompose()
    assert (
        tree.css_first("a[href='/clinicians/form']") is None
        and tree.css_first("a[href='/organizations/form']") is None
    ), "self-only Add CTAs must not render on another user's profile"


async def test_non_admin_forbidden_on_other_user_detail(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The security boundary: a non-admin GET on another user's detail
    page is 403. Enforced by `USER_ENTITY.detail_authz` (raising
    `assert_self_or_admin`) inside `handle_detail`. Pin both the status
    code and that the target's identifying fields (username, email) do
    not appear in the 403 body."""
    target_email = f"private-{uuid.uuid4()}@example.com"
    target_username = f"target-{uuid.uuid4()}"
    target = create_test_user(username=target_username, email=target_email)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")

    assert response.status_code == 403
    assert target_email not in response.text
    assert target_username not in response.text


async def test_self_detail_still_works(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """Non-admins must keep access to their own `/users/{own-id}` page
    — the `detail_authz` gate permits self even without admin."""
    response = await authenticated_client.get(f"/users/{logged_in_user.id}")
    assert response.status_code == 200
    assert logged_in_user.username in response.text


async def test_admin_detail_admin_actions_not_on_self_view(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Admin viewing their own detail does not see admin actions —
    they cannot deactivate / delete themselves. The companion
    `test_get_users_id_renders_admin_view_of_other_user` pins the
    inverse (admin viewing someone else)."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    response = await authenticated_client.get(f"/users/{logged_in_user.id}")
    tree = HTMLParser(response.text)
    assert (
        tree.css_first(f"button[hx-put='/users/{logged_in_user.id}/activation']")
        is None
    )


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


async def _seed_user_organization(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    name: str,
) -> uuid.UUID:
    org = make_organization_row(owner_id=user_id, name=name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(org)
        await session.refresh(org)
        return org.id


async def test_get_my_clinicians_empty_state(
    superuser_client: AsyncClient,
    superuser_logged_in_user: User,
):
    """`GET /users/me/clinicians` renders the empty state when the
    current user owns no clinicians."""
    response = await superuser_client.get("/users/me/clinicians")

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
    superuser_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    superuser_logged_in_user: User,
):
    """Self viewing their own clinician list sees a 'Create clinician'
    toolbar action — present both in the empty state and after the
    user has created one (so they can create additional clinicians)."""
    empty_response = await superuser_client.get("/users/me/clinicians")
    empty_tree = HTMLParser(empty_response.text)
    empty_action = _create_clinician_action(empty_tree)
    assert empty_action is not None
    assert empty_action.attributes.get("href") == "/clinicians/form"

    await _seed_user_clinician(
        db_test_session_manager,
        user_id=superuser_logged_in_user.id,
        practice_name="First",
    )

    with_one_response = await superuser_client.get("/users/me/clinicians")
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
    assert len(tree.css("#user-clinicians-list article")) == 1


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
    assert len(tree.css("#user-clinicians-list article")) == 1


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
    superuser_client: AsyncClient,
    superuser_logged_in_user: User,
):
    """`GET /users/me/clinicians` renders a breadcrumb back-affordance
    pointing at the current user's profile — auto-injected by
    `mount_related_list` via `USER_ENTITY.display_label_fn`."""
    response = await superuser_client.get("/users/me/clinicians")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    back = tree.css_first('nav[aria-label="breadcrumb"] a.breadcrumb-back')
    assert (
        back is not None
    ), "user clinicians list must render a breadcrumb back-affordance"
    assert back.attributes.get("href") == f"/users/{superuser_logged_in_user.id}"
    label = back.css_first("span.breadcrumb-back-label")
    assert (
        label is not None
        and label.text(strip=True) == superuser_logged_in_user.username
    )
