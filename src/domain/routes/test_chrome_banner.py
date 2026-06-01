"""Pins the profile-as-verification-state-view contract.

`/profile` is the single place where all verification state lives:
email confirmation, NPI, license. The global chrome no longer carries
a nag banner — `_verify_banner.html` was removed. These tests assert:

1. `/home` still shows the "Finish setting up" card for a no-claim user
   (that copy lives in `home.html`, not in the old banner).
2. `/profile` shows the email-verify section for unverified users and
   hides it for verified users (dev users are auto-verified).
3. Post CTAs on `/home` are gated on `claims.a` being populated.
"""

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser

from tests.helpers import (  # noqa: F401  (kept available for future tests)
    promote_to_admin,
)

pytestmark = pytest.mark.asyncio


async def test_new_user_sees_finish_setup_card_on_home(
    authenticated_client: AsyncClient,
):
    """A fresh dev user (no claims) lands on `/home` with the
    no-claim Finish-setup card pointing at `/profile`."""
    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    assert "Finish setting up" in response.text
    assert "Open Profile" in response.text


async def test_profile_email_verify_hidden_for_verified_user(
    authenticated_client: AsyncClient,
):
    """Dev users are auto-verified on registration, so the email-verify
    section on `/profile` should not appear for them."""
    response = await authenticated_client.get("/profile")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("#verify-banner") is None


async def test_profile_email_verify_shown_for_unverified_user(
    authenticated_client: AsyncClient,
    db_test_session_manager,
    logged_in_user,
):
    """An unverified user sees the email-verify section on `/profile`
    with a resend button."""
    from sqlalchemy import select

    from src.domain.models import User

    async with db_test_session_manager() as session:
        async with session.begin():
            fresh_user = (
                await session.execute(select(User).where(User.id == logged_in_user.id))
            ).scalar_one()
            fresh_user.is_verified = False

    response = await authenticated_client.get("/profile")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("#verify-banner") is not None
    assert "Verify your email" in response.text
    assert "Resend verification email" in response.text


async def test_home_renders_post_ctas_when_claim_a_verified(
    authenticated_client: AsyncClient,
    db_test_session_manager,
    logged_in_user,
):
    """A verified clinician sees the post CTAs on /home. The chrome's
    `claims.a` scalar is the gate — same predicate the route's
    write_authz consults, so visible button and server-side block
    can't disagree."""
    from tests.helpers import make_clinician_with_org

    clinician = make_clinician_with_org(owner_id=logged_in_user.id, npi="1234567890")
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = True
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    assert "+ Post a referral" in response.text
    assert "+ Post an opening" in response.text
