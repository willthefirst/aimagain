"""Pins the profile-as-verification-state-view contract.

`/profile` is the single place where all verification state lives:
email confirmation, NPI, license. The global chrome carries one
registry-driven incomplete-profile banner (`#onboarding-banner`, copy in
`base.html`, gated on `onboarding_incomplete` from `base_context` →
`onboarding_checklist`); it is suppressed on `/profile` itself, where the
full checklist is already on screen. The old `_verify_banner.html`
remains removed — this banner is the single consolidated signal, not its
return. These tests assert:

1. `/home` still shows the "Finish setting up" card for a no-claim user
   (that copy lives in `home.html`, not in the old banner).
2. `/profile` shows the email-verify section for unverified users and
   hides it for verified users (dev users are auto-verified).
3. Post CTAs on `/home` are gated on `claims.a` being populated.
4. The global `#onboarding-banner` shows for an incomplete authed user
   off `/profile`, hides on `/profile`, and hides once a claim verifies.
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


async def test_profile_email_row_links_to_step_for_unverified_user(
    authenticated_client: AsyncClient,
    db_test_session_manager,
    logged_in_user,
):
    """For an unverified user the `/profile` table of contents shows the
    email row as an incomplete link to the `/profile/email` step page —
    no inline resend on the hub. The resend control lives on the step page
    (asserted by the step-page test below)."""
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
    # The hub is a pure index now — no embedded resend form.
    assert tree.css_first("#verify-banner") is None
    # The email row is incomplete and links out to its step subroute.
    email_row = tree.css_first('#onboarding-checklist [data-step="email"]')
    assert email_row is not None
    link = email_row.css_first("a.onboarding-progress-link")
    assert link is not None
    assert link.attributes.get("href") == "/profile/email"


async def test_profile_email_step_page_hosts_resend_for_unverified_user(
    authenticated_client: AsyncClient,
    db_test_session_manager,
    logged_in_user,
):
    """The `/profile/email` step page hosts the resend control with the
    `#verify-banner` swap target. The resend stays a passive outline button
    so it doesn't shout."""
    from sqlalchemy import select

    from src.domain.models import User

    async with db_test_session_manager() as session:
        async with session.begin():
            fresh_user = (
                await session.execute(select(User).where(User.id == logged_in_user.id))
            ).scalar_one()
            fresh_user.is_verified = False

    response = await authenticated_client.get("/profile/email")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert "Verify your email" in response.text
    assert "Resend verification email" in response.text
    resend = tree.css_first("#verify-banner button[type=submit]")
    assert resend is not None
    classes = resend.attributes.get("class", "")
    assert "outline" in classes
    assert "verify-resend" in classes


async def test_profile_email_step_redirects_to_hub_when_verified(
    authenticated_client: AsyncClient,
):
    """A verified user has nothing to do on `/profile/email`, so it
    redirects back to the hub table of contents."""
    response = await authenticated_client.get("/profile/email", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/profile"


async def test_home_shows_empty_my_posts_section_when_no_active_posts(
    authenticated_client: AsyncClient,
    db_test_session_manager,
    logged_in_user,
):
    """A verified clinician with no posts sees the 'My active posts' section
    with an empty state message and a create CTA — not a hidden section."""
    from tests.helpers import make_clinician_with_org

    clinician = make_clinician_with_org(owner_id=logged_in_user.id, npi="1234567890")
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = True
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    assert "My active posts" in response.text
    assert "You have no active posts." in response.text
    assert "Create a post" in response.text


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


async def test_home_shows_locked_post_actions_for_claim_b_only_org_rep(
    authenticated_client: AsyncClient,
    db_test_session_manager,
    logged_in_user,
):
    """A Claim-B-only org rep (verified org representative, no Claim A)
    can't post as themselves, but the chrome no longer hides the actions —
    it renders them DISABLED with the unlock path (`locked_action` →
    `_shared/_locked.html`). Pins: the buttons render disabled (not as
    active create links), and the unlock copy comes from
    `capabilities.reason_meta`, not inline text."""
    from src.domain.logic import capabilities
    from src.domain.models.org_representations.org_representation import (
        OrgRepresentation,
    )
    from tests.helpers import make_organization_row

    org = make_organization_row(owner_id=logged_in_user.id)
    rep = OrgRepresentation(
        user_id=logged_in_user.id,
        org_id=org.id,
        role="coordinator",
        authority_method="admin_review",
        authority_status="verified",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(org)
            session.add(rep)

    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    # Claim-B-only → has a claim, so NOT the no-claim finish-setup card.
    assert "Finish setting up" not in response.text

    # Both post actions render as DISABLED buttons, not active create links.
    disabled_labels = {
        b.text(strip=True)
        for b in tree.css("button[disabled]")
        if b.text(strip=True).startswith("+ Post")
    }
    assert "+ Post a referral" in disabled_labels
    assert "+ Post an opening" in disabled_labels
    assert (
        tree.css_first("a[href*='kind=referral']") is None
    ), "Claim-B-only rep must not get an active post-create link"

    # Unlock copy is the single-source string, not inline-authored here.
    assert (
        capabilities.reason_meta(capabilities.REASON_CLAIM_A_UNVERIFIED).unlock
        in response.text
    )


async def test_onboarding_banner_shown_off_profile_for_incomplete_user(
    authenticated_client: AsyncClient,
):
    """A fresh dev user (email auto-verified, no claim) is onboarding-
    incomplete, so the global banner shows on a non-`/profile` page and
    links into the hub."""
    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    banner = tree.css_first("#onboarding-banner")
    assert banner is not None
    assert banner.css_first("a").attributes["href"].startswith("/profile")


async def test_onboarding_banner_suppressed_on_profile(
    authenticated_client: AsyncClient,
):
    """The banner never renders on `/profile` itself — the full checklist
    is already on screen there."""
    response = await authenticated_client.get("/profile")
    assert response.status_code == 200
    assert HTMLParser(response.text).css_first("#onboarding-banner") is None


async def test_onboarding_banner_hidden_once_claim_verified(
    authenticated_client: AsyncClient,
    db_test_session_manager,
    logged_in_user,
):
    """A verified clinician has completed onboarding, so the global banner
    is silent even off `/profile`."""
    from tests.helpers import make_clinician_with_org

    clinician = make_clinician_with_org(owner_id=logged_in_user.id, npi="1234567890")
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = True
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    assert HTMLParser(response.text).css_first("#onboarding-banner") is None


async def test_profile_checklist_shows_remaining_steps_for_incomplete_user(
    authenticated_client: AsyncClient,
):
    """The registry-driven progress overview on `/profile` lists the spine
    steps with their done/remaining state. A fresh dev user has email done
    and identity pending."""
    response = await authenticated_client.get("/profile")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    checklist = tree.css_first("#onboarding-checklist")
    assert checklist is not None
    email_row = checklist.css_first('[data-step="email"]')
    identity_row = checklist.css_first('[data-step="identity"]')
    assert "is-complete" in email_row.attributes["class"]
    assert "is-pending" in identity_row.attributes["class"]


async def test_profile_checklist_hidden_when_onboarding_complete(
    authenticated_client: AsyncClient,
    db_test_session_manager,
    logged_in_user,
):
    """A verified clinician has nothing left to track, so the progress
    overview is omitted (manage mode)."""
    from tests.helpers import make_clinician_with_org

    clinician = make_clinician_with_org(owner_id=logged_in_user.id, npi="1234567890")
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = True
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/profile")
    assert response.status_code == 200
    assert HTMLParser(response.text).css_first("#onboarding-checklist") is None
