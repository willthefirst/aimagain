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
