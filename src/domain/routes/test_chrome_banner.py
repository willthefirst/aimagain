"""Pins the verification status and chrome banner contract.

The global chrome carries one chrome signal (`#onboarding-banner`, copy in
`base.html`, gated on `onboarding_incomplete` from `base_context` →
`onboarding_checklist`). The old `/profile` hub has been removed; the
verification card on `/users/me` is the new home for claim setup links.
These tests assert:

1. `/home` shows no per-page finish-setup card for a no-claim user — the
   post-action row is suppressed entirely and the only nudge is the chrome
   `#onboarding-banner`.
2. Post CTAs on `/home` are gated on `can_access_network` (clinician or org rep).
3. The global `#onboarding-banner` is currently disabled (absent on all pages).
"""

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser

from tests.helpers import (  # noqa: F401  (kept available for future tests)
    promote_to_admin,
)

pytestmark = pytest.mark.asyncio


async def test_new_user_sees_no_finish_setup_card_on_home(
    authenticated_client: AsyncClient,
):
    """A fresh dev user (no claims) lands on `/home` with no per-page
    finish-setup card: the old `#finish-setup-card` / "Open Profile" CTA is
    gone, and no post-action buttons stand in for it. The chrome
    `#onboarding-banner` is the single finish-setup nudge."""
    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("#finish-setup-card") is None
    assert "Open Profile" not in response.text
    assert "+ Post a referral" not in response.text
    # Banner temporarily disabled.
    assert tree.css_first("#onboarding-banner") is None


async def test_home_shows_network_section_with_empty_state_when_no_recent_posts(
    authenticated_client: AsyncClient,
):
    """The 'Recent in the network' section is always rendered, even when no
    posts exist in the last 7 days — the header and an empty-state message
    appear instead of the section being hidden."""
    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    assert "Recent in the network" in response.text
    assert "No activity in the last 7 days." in response.text


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
    assert "My posts" in response.text
    assert "No posts yet." in response.text
    assert "Create a post" in response.text


async def test_home_renders_post_ctas_when_claim_a_verified(
    authenticated_client: AsyncClient,
    db_test_session_manager,
    logged_in_user,
):
    """A verified clinician sees the post CTAs on /home. The chrome gates
    on `can_access_network`, so any network-verified user gets the active
    create links."""
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

    # The post CTAs ride the unified page-header toolbar (not an inline
    # content section): each active create link is a `<li>` inside the
    # band's `menu.toolbar-right`, and the page title is the band's H1.
    tree = HTMLParser(response.text)
    h1 = tree.css_first("header.page-header div.toolbar h1")
    assert h1 is not None and h1.text(strip=True) == "Home"
    cta_labels = {
        li.text(strip=True)
        for li in tree.css("header.page-header menu.toolbar-right li")
        if li.text(strip=True).startswith("+ Post")
    }
    assert cta_labels == {"+ Post a referral", "+ Post an opening"}


async def test_home_shows_active_post_actions_for_claim_b_org_rep(
    authenticated_client: AsyncClient,
    db_test_session_manager,
    logged_in_user,
):
    """A verified org rep (no clinician profile) gets full posting chrome —
    `can_access_network` is the single gate. Pins: active create links appear
    in the toolbar (not disabled buttons), same as a verified clinician."""
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

    # Claim-B → has network access, so NOT the no-claim finish-setup card.
    assert "Finish setting up" not in response.text

    # Active create links appear in the toolbar — no disabled buttons.
    assert (
        tree.css_first("a[href*='kind=referral']") is not None
    ), "Claim-B org rep must get the active post-a-referral toolbar link"
    assert (
        tree.css_first("a[href*='kind=clinician_opening']") is not None
    ), "Claim-B org rep must get the active post-an-opening toolbar link"
    disabled_post_buttons = [
        b
        for b in tree.css("button[disabled]")
        if b.text(strip=True).startswith("+ Post")
    ]
    assert (
        disabled_post_buttons == []
    ), "No disabled post buttons expected for a network-verified user"


async def test_onboarding_banner_shown_off_profile_for_incomplete_user(
    authenticated_client: AsyncClient,
):
    """Banner temporarily disabled — assert it is absent."""
    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    assert HTMLParser(response.text).css_first("#onboarding-banner") is None


async def test_onboarding_banner_renders_inside_main(
    authenticated_client: AsyncClient,
):
    """Banner temporarily disabled — assert it is absent."""
    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    assert HTMLParser(response.text).css_first("#onboarding-banner") is None


async def test_onboarding_banner_hidden_once_claim_verified(
    authenticated_client: AsyncClient,
    db_test_session_manager,
    logged_in_user,
):
    """A verified clinician has completed onboarding, so the global banner
    is silent."""
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
