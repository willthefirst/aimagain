import pytest
from fastapi_users.db import SQLAlchemyUserDatabase
from httpx import AsyncClient
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import User
from src.framework.audit.log import AuditLog
from src.framework.audit.repository import AuditRepository

pytestmark = pytest.mark.asyncio


class UserCreateRequest(BaseModel):
    email: str
    password: str


async def test_register(
    test_client: AsyncClient, db_test_session_manager: async_sessionmaker[AsyncSession]
):
    email_to_test = "testreg@example.com"
    password_to_test = "password123"

    register_data = {
        "email": email_to_test,
        "password": password_to_test,
    }
    response = await test_client.post("/auth/register", json=register_data)
    assert response.status_code == 201
    assert "application/json" in response.headers["content-type"]
    user_info = response.json()
    assert user_info["email"] == email_to_test
    assert user_info["is_active"] is True
    assert user_info["is_superuser"] is False
    # Signup form no longer collects a username; `handle_registration`
    # fills the (UNIQUE, NOT NULL) column from `email` so existing
    # downstream consumers (display, audit snapshot, emails) keep working.
    assert user_info["username"] == email_to_test
    # `is_verified` restored to the response with the verification
    # rollout (reversing #696). Tests run with `ENVIRONMENT=development`
    # (see `.env.test`), so the dev-mode auto-verify guardrail in
    # `UserManager.on_after_register` fires — the user is `True`
    # without anyone clicking a verify link. In production this would
    # be `False` until the user clicks the link in their verify email;
    # the prod path is exercised by `test_register_prod_mode_leaves_user_unverified`.
    assert user_info["is_verified"] is True

    async with db_test_session_manager() as session:
        user_db = SQLAlchemyUserDatabase(session, User)
        created_user = await user_db.get_by_email(email_to_test)
        assert created_user is not None
        assert created_user.email == email_to_test


async def test_register_prod_mode_leaves_user_unverified(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    monkeypatch,
):
    """Pin the production-mode path: `on_after_register` calls
    `self.request_verify` (which sends the verify email) and does NOT
    auto-flip `is_verified`. The user starts at `False` until they
    click the link in the email.

    Tests run with `ENVIRONMENT=development` by default — this test
    monkey-patches that and stubs the send call so the assertion
    isolates the hook's branching, not the email transport."""
    from unittest.mock import AsyncMock

    monkeypatch.setattr("src.auth_config.settings.ENVIRONMENT", "production")
    monkeypatch.setattr(
        "src.domain.logic.auth.emails.send_email", AsyncMock(return_value=None)
    )

    register_data = {
        "email": "prod-mode-user@example.com",
        "password": "password123",
    }
    response = await test_client.post("/auth/register", json=register_data)
    assert response.status_code == 201
    assert response.json()["is_verified"] is False


async def test_register_via_htmx_sets_cookie_and_redirects(test_client: AsyncClient):
    """HTMX register should auto-login (cookie) and redirect, not return JSON."""
    payload = {
        "email": "htmx@example.com",
        "password": "Password123!",
    }
    response = await test_client.post(
        "/auth/register",
        json=payload,
        headers={"HX-Request": "true", "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.headers.get("HX-Redirect") == "/users/me"
    # A session cookie must be set so the redirect lands authenticated.
    assert (
        "fastapiusersauth" in response.cookies
        or "set-cookie" in str(response.headers).lower()
    )


async def test_register_duplicate_email(test_client: AsyncClient, logged_in_user: User):
    register_data = {
        "email": logged_in_user.email,
        "password": "newpassword",
    }
    response = await test_client.post("/auth/register", json=register_data)
    assert response.status_code == 400


async def test_login_success(test_client: AsyncClient, logged_in_user: User):
    login_data = {
        "username": logged_in_user.email,
        "password": "password123",
    }
    response = await test_client.post("/auth/jwt/login", data=login_data)
    assert response.status_code == 302
    assert response.headers["Set-Cookie"] is not None
    assert "fastapiusersauth=" in response.headers["Set-Cookie"]
    access_token = response.headers["Set-Cookie"].split(";")[0].split("=")[1]
    assert access_token is not None

    auth_header = {"Cookie": f"fastapiusersauth={access_token}"}
    me_response = await test_client.get("/users/me", headers=auth_header)
    assert me_response.status_code == 200
    assert logged_in_user.email in me_response.text


async def test_login_failure_wrong_password(
    test_client: AsyncClient, logged_in_user: User
):
    login_data = {
        "username": logged_in_user.email,
        "password": "wrongpassword",
    }
    response = await test_client.post("/auth/jwt/login", data=login_data)
    assert response.status_code == 400


async def test_login_failure_nonexistent_user(test_client: AsyncClient):
    login_data = {
        "username": "nosuchuser@example.com",
        "password": "password123",
    }
    response = await test_client.post("/auth/jwt/login", data=login_data)
    assert response.status_code == 400


async def test_logout_success(authenticated_client: AsyncClient):
    me_response_before = await authenticated_client.get("/users/me")
    assert me_response_before.status_code == 200
    user_email_html = me_response_before.text

    logout_response = await authenticated_client.post("/auth/jwt/logout")
    assert logout_response.status_code == 204
    assert not logout_response.content

    me_response_after = await authenticated_client.get("/users/me")
    assert me_response_after.status_code == 200
    assert me_response_after.text == user_email_html


async def test_authenticated_page_has_sign_out_affordance(
    authenticated_client: AsyncClient,
):
    """Any authenticated page must expose the sign-out endpoint in the
    header chrome so the user can end their session within 2 clicks.
    Sign-out is a plain `<a hx-post="/auth/sign-out">` in the primary
    nav row; the route returns `HX-Redirect` and HTMX handles the
    full-page navigation to `/auth/login`."""
    response = await authenticated_client.get(
        "/users/me", headers={"Accept": "text/html"}
    )
    assert response.status_code == 200
    assert 'hx-post="/auth/sign-out"' in response.text


async def test_forgot_password_request(test_client: AsyncClient, logged_in_user: User):
    response = await test_client.post(
        "/auth/forgot-password", json={"email": logged_in_user.email}
    )
    assert response.status_code == 202


async def test_forgot_password_request_nonexistent_user(test_client: AsyncClient):
    response = await test_client.post(
        "/auth/forgot-password", json={"email": "nosuchuser@example.com"}
    )
    # Should still return 202 Accepted to avoid leaking user existence information.
    assert response.status_code == 202


async def test_reset_password(test_client: AsyncClient, logged_in_user: User):
    request_response = await test_client.post(
        "/auth/forgot-password", json={"email": logged_in_user.email}
    )
    assert request_response.status_code == 202

    reset_token = "VALID_RESET_TOKEN"
    if reset_token == "VALID_RESET_TOKEN":
        pytest.skip("Password reset token retrieval not implemented for testing")

    new_password = "newSecurePassword123"
    reset_data = {"token": reset_token, "password": new_password}
    reset_response = await test_client.post("/auth/reset-password", json=reset_data)
    assert reset_response.status_code == 200

    login_data = {"username": logged_in_user.email, "password": new_password}
    login_response = await test_client.post("/auth/jwt/login", data=login_data)
    assert login_response.status_code == 200
    assert "access_token" in login_response.json()


async def test_reset_password_invalid_token(test_client: AsyncClient):
    reset_data = {"token": "INVALID_TOKEN", "password": "newpassword"}
    response = await test_client.post("/auth/reset-password", json=reset_data)
    assert response.status_code == 400


async def test_get_register_page(test_client: AsyncClient):
    response = await test_client.get("/auth/register")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # Page H1 plus the canonical "Create account" submit button are
    # both load-bearing — pin the H1 here so the page-title copy
    # doesn't drift to a generic "Sign up" / "Register" string. The
    # rest of the auth-flow pages follow the same shape.
    assert "Create an account" in response.text
    assert "Create account" in response.text
    # Form wrapper — `.auth-page` caps the form at 28rem and centers it
    # so it doesn't stretch to the `<main class="container">` width on
    # tablet/desktop (#584). No card chrome: deliberately not styled as
    # a card. The `.auth-page` rule lives in `base.html`.
    assert '<section class="auth-page">' in response.text
    # Subtitle must use plain language a first-time visitor can parse —
    # no bare model-jargon list ("openings, referrals, and intakes")
    # before any value framing (#694).
    assert "openings, referrals, and intakes" not in response.text
    assert "clinician profile" in response.text
    # Signup form collects email + password only — username is filled
    # server-side from email in `handle_registration`. Pin the absence
    # so the field doesn't sneak back in.
    assert 'name="username"' not in response.text


async def test_get_login_page(test_client: AsyncClient):
    response = await test_client.get("/auth/login")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # H1 + submit button (both "Log in" — verb form, no longer the
    # noun "Login"). See `test_get_register_page` for the H1 pin
    # rationale.
    assert "Log in" in response.text
    # Default subtitle must not assume a returning user (#693).
    assert "Welcome back" not in response.text
    assert "referrals" not in response.text
    assert "Sign in to your Bedlam Connect account" in response.text
    # See `test_get_register_page` for `.auth-page` rationale (#584).
    assert '<section class="auth-page">' in response.text
    # Default subtitle must not assume a returning user (#693).
    assert "Welcome back" not in response.text
    # Default subtitle must not contain bare jargon without context (#693).
    assert "referrals" not in response.text
    assert "Sign in to your Bedlam Connect account" in response.text


async def test_get_login_page_post_register_banner(test_client: AsyncClient):
    """?registered=1 shows a confirmation banner instead of the default subtitle."""
    response = await test_client.get("/auth/login?registered=1")
    assert response.status_code == 200
    assert "Account created" in response.text
    assert "Sign in to your Bedlam Connect account." not in response.text


async def test_get_login_page_just_registered(test_client: AsyncClient):
    """GET /auth/login?registered=1 shows the post-registration banner (#693)."""
    response = await test_client.get("/auth/login?registered=1")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Account created" in response.text
    # Default subtitle is replaced by the contextual message.
    assert "Sign in to your Bedlam Connect account" not in response.text


async def test_get_forgot_password_page(test_client: AsyncClient):
    response = await test_client.get("/auth/forgot-password")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # H1 was removed app-wide; the page no longer carries the literal
    # "Forgot password" text. The submit button and body copy still
    # identify the page.
    assert "Send reset link" in response.text
    # See `test_get_register_page` for `.auth-page` rationale (#584).
    assert '<section class="auth-page">' in response.text
    # The form MUST submit as JSON — fastapi-users' `/auth/forgot-password`
    # expects `{"email": "..."}`. A plain `<form method="post">` would
    # send `application/x-www-form-urlencoded` and the endpoint would
    # 422 with "email field required" in production. Pin both the
    # htmx submit attribute and the json-enc extension so the next
    # rewrite can't silently regress to form-encoding.
    assert 'hx-post="/auth/forgot-password"' in response.text
    assert 'hx-ext="json-enc"' in response.text


async def test_get_reset_password_page(test_client: AsyncClient):
    reset_token = "SOME_TOKEN_FOR_TESTING_URL"
    response = await test_client.get(f"/auth/reset-password/{reset_token}")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # H1 + submit button. Reset is now "Save password" (the user is
    # picking a new password, not resetting one); the H1 sets the
    # "you're about to" frame.
    assert "Set a new password" in response.text
    assert "Save password" in response.text
    assert (
        f'value="{reset_token}"' in response.text
        or f'data-token="{reset_token}"' in response.text
    )
    # Same JSON-submit contract as `test_get_forgot_password_page`:
    # the endpoint expects `{"token": "...", "password": "..."}` and
    # form-encoding would 422.
    assert 'hx-post="/auth/reset-password"' in response.text
    assert 'hx-ext="json-enc"' in response.text
    # See `test_get_register_page` for `.auth-page` rationale (#584).
    assert '<section class="auth-page">' in response.text


async def test_card_chrome_only_applies_to_article_list_items(
    test_client: AsyncClient,
):
    """Card chrome (background, border, padding, header/footer bands)
    is reserved for list-item cards — `<article class="entity-card">`
    rendered via `_shared/_card.html` — which pick it up automatically
    from Pico's default `<article>` element styling. Single-item
    wrappers (`<section class="entity-card">` detail pages,
    `<section class="auth-page">` auth pages) carry the class as a DOM
    hook only, contributing no styling.

    Pin the rule by asserting the inline `<style>` block in the
    rendered page contains no `.entity-card` rule whose body has card-
    chrome properties (background, box-shadow, border-radius, padding).
    If someone re-adds chrome to `.entity-card`, the regex match fires
    and this test fails."""
    import re

    response = await test_client.get("/auth/login")
    assert response.status_code == 200
    # Find any `.entity-card` rule (matches `.entity-card { ... }` or
    # `.entity-card > header { ... }`); assert none of them carry
    # chrome properties. A bare `.entity-card,` in a combined selector
    # (e.g. `.entity-card, .auth-page { background: ... }`) would also
    # match. The auth-page max-width rule isn't on entity-card so it
    # doesn't fire this.
    chrome_props = ("background:", "box-shadow:", "border-radius:", "padding:")
    for match in re.finditer(r"\.entity-card[^{]*\{([^}]*)\}", response.text):
        body = match.group(1)
        offenders = [p for p in chrome_props if p in body]
        assert not offenders, (
            f".entity-card rule has chrome properties {offenders}: "
            f"`{match.group(0).strip()}` — chrome belongs only on the "
            "Pico `<article>` element default, not on the class."
        )


async def test_get_verify_page_without_token_returns_error(test_client: AsyncClient):
    """Missing `?token=` query param → error state. Page still
    renders 200 (this is the email-link landing, not an API endpoint
    — the user shouldn't see a JSON 422)."""
    response = await test_client.get("/auth/verify")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "didn't work" in response.text.lower() or "error" in response.text.lower()


async def test_get_verify_page_with_invalid_token_returns_error(
    test_client: AsyncClient,
):
    """An obviously-bad token (not a valid JWT) renders the error
    state, never raises a 500. The page route swallows
    `InvalidVerifyToken` and routes to the error template."""
    response = await test_client.get("/auth/verify?token=not.a.real.jwt")
    assert response.status_code == 200
    assert "didn't work" in response.text.lower() or "error" in response.text.lower()


async def test_get_verify_page_with_valid_token_verifies_user(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A valid verification token flips `is_verified` to True and the
    landing page renders the success state."""
    from src.auth_config import get_user_manager
    from src.db import get_user_db

    # Mint a real verify token by calling `request_verify` through the
    # manager — same path the email-link generation uses.
    async with db_test_session_manager() as session:
        user_db_gen = get_user_db(session)
        user_db = await anext(user_db_gen)
        manager_gen = get_user_manager(user_db)
        manager = await anext(manager_gen)
        # Pull a fresh user row from this session so the manager can
        # operate on it without touching a closed session.
        from sqlalchemy import select

        fresh_user = (
            await session.execute(select(User).where(User.id == logged_in_user.id))
        ).scalar_one()
        # Mark unverified so the verify call has work to do (the dev
        # auto-verify pathway leaves users at True; reset to False here).
        await user_db.update(fresh_user, {"is_verified": False})
        # Mint the token via the manager. fastapi-users doesn't expose
        # a `make_verify_token` helper but `request_verify` produces
        # one and triggers `on_after_request_verify` — we capture the
        # token from there.

        captured: dict = {}

        async def capture_send(user, token):
            captured["token"] = token

        from src.domain.logic.auth import emails as emails_module

        original = emails_module.send_verification_email
        emails_module.send_verification_email = capture_send
        try:
            await manager.request_verify(fresh_user)
        finally:
            emails_module.send_verification_email = original

    token = captured["token"]

    response = await test_client.get(f"/auth/verify?token={token}")
    assert response.status_code == 200
    assert "verified" in response.text.lower()

    # Confirm the DB column actually flipped.
    async with db_test_session_manager() as session:
        from sqlalchemy import select

        user = (
            await session.execute(select(User).where(User.id == logged_in_user.id))
        ).scalar_one()
        assert user.is_verified is True


async def test_post_resend_verify_unauthenticated_returns_401(test_client: AsyncClient):
    """`POST /auth/resend-verify` reads the user from the session — no
    cookie means no resend. Returns 401 (handled by the middleware
    that turns 401 into a redirect for HTML, but the API client here
    isn't sending the HTMX header so it stays 401)."""
    response = await test_client.post("/auth/resend-verify")
    assert response.status_code == 401


async def test_post_resend_verify_authenticated_returns_sent_banner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
    monkeypatch,
):
    """Authed user can re-request the verify email. Response is the
    `_verify_banner_sent.html` partial (HTMX swaps it over the
    original banner via `outerHTML`)."""
    # Stub the actual send so the test doesn't print to stderr.
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "src.domain.logic.auth.emails.send_email", AsyncMock(return_value=None)
    )

    response = await authenticated_client.post("/auth/resend-verify")
    assert response.status_code == 200
    assert "Verification email sent" in response.text
    # The partial keeps the original id so a future HTMX target=
    # `#verify-banner` swap on the same page still works.
    assert 'id="verify-banner"' in response.text


async def test_unauthorized_redirect_for_browser_requests(test_client: AsyncClient):
    response = await test_client.get(
        "/users/me",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login?next=/users/me"


async def test_unauthorized_json_response_for_api_requests(test_client: AsyncClient):
    response = await test_client.get(
        "/users/me", headers={"Accept": "application/json"}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


async def test_unauthorized_default_behavior(test_client: AsyncClient):
    response = await test_client.get("/users/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


async def test_unauthorized_redirect_follows_to_login_page(test_client: AsyncClient):
    response = await test_client.get(
        "/users/me",
        headers={"Accept": "text/html"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Log in" in response.text


async def test_register_writes_audit_row(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Each successful POST /auth/register writes one audit row with
    actor_id=None (self-signup has no authenticated actor)."""
    register_data = {
        "email": "audit-target@example.com",
        "password": "password123",
        "username": "audittarget",
    }
    response = await test_client.post("/auth/register", json=register_data)
    assert response.status_code == 201
    new_user_id = response.json()["id"]

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        from uuid import UUID

        rows = await repo.list_for_resource(
            resource_type="user", resource_id=UUID(new_user_id)
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.actor_id is None
        assert row.action == "register"
        assert row.before is None
        assert row.after == {
            "username": "audittarget",
            "email": "audit-target@example.com",
            "is_active": True,
            "is_superuser": False,
        }


async def test_failed_register_writes_no_audit_row(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A 400 (duplicate email) must not leak an audit row."""
    register_data = {
        "email": logged_in_user.email,
        "password": "newpassword",
        "username": "duplicate",
    }
    response = await test_client.post("/auth/register", json=register_data)
    assert response.status_code == 400

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(AuditLog)
            .filter(AuditLog.action == "register")
            .filter(AuditLog.after["email"].as_string() == logged_in_user.email)
        )
        rows = result.scalars().all()
        assert rows == []


async def test_root_anonymous_returns_landing_page(test_client: AsyncClient):
    """Anonymous GET / returns the marketing landing page (200 HTML),
    not a redirect to the login wall (#692). The H1 + tagline +
    description copy are taken verbatim from the parent marketing
    site at https://www.bedlamconnect.com/ — pinning them so a
    well-meaning copy edit doesn't quietly drift the public-facing
    page out of sync with the brand."""
    response = await test_client.get("/", follow_redirects=False)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # Verbatim copy from bedlamconnect.com.
    assert "Welcome to Bedlam Connect" in response.text
    assert "Connecting providers, helping patients." in response.text
    assert (
        "Post referrals, find referrals, and maintain a network of "
        "professional contacts." in response.text
    )
    # Both CTAs must be present so anonymous visitors can self-serve.
    # "Sign in" / "Sign up" verbs match the parent marketing site and
    # the rest of the auth flow (#693).
    assert "/auth/register" in response.text
    assert "/auth/login" in response.text
    assert "Sign in" in response.text
    assert "Sign up" in response.text


async def test_root_authenticated_redirects_to_referrals(
    authenticated_client: AsyncClient,
):
    """Authenticated GET / still redirects to /referrals — the
    "find new clients" home (#692)."""
    response = await authenticated_client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/referrals"
