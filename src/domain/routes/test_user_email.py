"""Integration tests for GET /users/me/email/form."""

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import User

pytestmark = pytest.mark.asyncio


async def test_email_form_unauthenticated_is_rejected(test_client: AsyncClient):
    """Unauthenticated GET /users/me/email/form is bounced — not 200."""
    response = await test_client.get("/users/me/email/form", follow_redirects=False)
    assert response.status_code != 200


async def test_email_form_renders_for_self(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """GET /users/me/email/form returns 200 with the user's email displayed."""
    response = await authenticated_client.get("/users/me/email/form")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert logged_in_user.email in response.text


async def test_email_form_shows_resend_button_when_unverified(
    authenticated_client: AsyncClient,
    logged_in_user: User,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """An unverified user sees a 'Resend verification email' button that
    POSTs to /auth/resend-verify via HTMX."""
    async with db_test_session_manager() as session:
        async with session.begin():
            user = await session.get(User, logged_in_user.id)
            user.is_verified = False

    response = await authenticated_client.get("/users/me/email/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    resend = tree.css_first("button[hx-post='/auth/resend-verify']")
    assert (
        resend is not None
    ), "unverified user should see Resend verification email button"


async def test_email_form_omits_resend_when_verified(
    authenticated_client: AsyncClient,
    logged_in_user: User,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A verified user does not see the resend button — nothing to resend."""
    async with db_test_session_manager() as session:
        async with session.begin():
            user = await session.get(User, logged_in_user.id)
            user.is_verified = True

    response = await authenticated_client.get("/users/me/email/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    resend = tree.css_first("button[hx-post='/auth/resend-verify']")
    assert resend is None, "verified user should not see Resend button"


async def test_email_form_breadcrumb_points_to_profile(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """The email form breadcrumb chain links its profile segment to the
    user's own page (chain: Home → … → profile → Email)."""
    response = await authenticated_client.get("/users/me/email/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    nav = tree.css_first('nav[aria-label="breadcrumb"]')
    assert nav is not None
    assert any(
        a.attributes.get("href") == f"/users/{logged_in_user.id}" for a in nav.css("a")
    ), "breadcrumb must link to the user's profile"


# --- Inbox CTA (post-register / post-resend) -----------------------------
#
# The page doubles as the destination both `POST /auth/register` and
# `POST /auth/resend-verify` redirect to. When the viewer is unverified
# it renders an "open your inbox" affordance — smart link for recognized
# webmail providers, plain sentence otherwise. `?sent=1` swaps the lede
# to a "just sent" confirmation.


async def test_email_form_renders_smart_link_for_gmail(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Unverified Gmail user sees an "Open Gmail" button whose href is a
    pre-filtered search URL for the verify sender."""
    async with db_test_session_manager() as session:
        async with session.begin():
            user = await session.get(User, logged_in_user.id)
            user.email = "alice@gmail.com"
            user.is_verified = False

    response = await authenticated_client.get("/users/me/email/form")
    assert response.status_code == 200
    assert "Open Gmail" in response.text
    # The Gmail search URL is pinned in test_email_providers.py; here we
    # just verify the template actually renders it.
    assert "mail.google.com/mail/u/0/#search/" in response.text
    assert "from%3Ano-reply%40bedlamconnect.com" in response.text
    assert "alice@gmail.com" in response.text


async def test_email_form_falls_back_for_unknown_domain(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Unverified user on an unrecognized domain (default fixture user
    is `@example.com`) → no button, plain sentence referencing the
    from address."""
    async with db_test_session_manager() as session:
        async with session.begin():
            user = await session.get(User, logged_in_user.id)
            user.is_verified = False

    response = await authenticated_client.get("/users/me/email/form")
    assert response.status_code == 200
    assert "Open Gmail" not in response.text
    assert "mail.google.com" not in response.text
    # The from address is named in the plain-sentence fallback.
    assert "no-reply@bedlamconnect.com" in response.text
    # The user's email is still surfaced so they know which address to check.
    assert logged_in_user.email in response.text


async def test_email_form_shows_just_sent_banner_with_query_flag(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`?sent=1` (set by the resend redirect) renders the "just sent"
    status line."""
    async with db_test_session_manager() as session:
        async with session.begin():
            user = await session.get(User, logged_in_user.id)
            user.is_verified = False

    response = await authenticated_client.get("/users/me/email/form?sent=1")
    assert response.status_code == 200
    assert "Verification email sent" in response.text


async def test_email_form_omits_just_sent_banner_without_query_flag(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The "just sent" status is opt-in via `?sent=1`; first-visit
    (post-registration redirect) doesn't show it."""
    async with db_test_session_manager() as session:
        async with session.begin():
            user = await session.get(User, logged_in_user.id)
            user.is_verified = False

    response = await authenticated_client.get("/users/me/email/form")
    assert response.status_code == 200
    assert "Verification email sent" not in response.text


async def test_email_form_omits_inbox_cta_when_verified(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Verified users have nothing to nudge — neither inbox CTA nor
    "just sent" banner should appear, even with `?sent=1`."""
    async with db_test_session_manager() as session:
        async with session.begin():
            user = await session.get(User, logged_in_user.id)
            user.email = "alice@gmail.com"
            user.is_verified = True

    response = await authenticated_client.get("/users/me/email/form?sent=1")
    assert response.status_code == 200
    assert "Open Gmail" not in response.text
    assert "Verification email sent" not in response.text
