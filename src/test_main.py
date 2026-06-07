"""Pins the `lifespan` scheduler-gating contract: DISABLE_SCHEDULER=1 skips
the subsystem entirely (no construction, no registration, no start), while
the default path constructs + registers + starts. The contract matters
because APScheduler's `add_job` logs "Adding job tentatively…" whenever a
job is registered against a not-yet-started scheduler — calling
`register_jobs` on a disabled scheduler is observable noise.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from selectolax.parser import HTMLParser

from src.domain.models import Post
from src.main import lifespan

pytestmark = pytest.mark.asyncio


# --- GET /home -----------------------------------------------------------


async def test_home_page_requires_auth(test_client: AsyncClient):
    """Unauthenticated browser requests to /home redirect to the login page.
    The 401→302 rewrite fires only when Accept: text/html is present
    (see `unauthorized_exception_handler` in main.py)."""
    response = await test_client.get(
        "/home",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]


async def test_home_page_shows_post_buttons_when_claim_a_verified(
    authenticated_client: AsyncClient,
    db_test_session_manager,
    logged_in_user,
):
    """The home page renders kind-specific CTAs linking to the unified
    `/posts/form` URL when the user is network-verified. CTAs are gated
    on `can_access_network` from `base_context()` — same
    predicate the route's `write_authz` consults — so the visible button
    and the server-side block can't disagree."""
    from tests.helpers import make_clinician_with_org

    clinician = make_clinician_with_org(owner_id=logged_in_user.id, npi="1234567890")
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = True
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first('a[href="/posts/form?kind=referral"]') is not None
    assert tree.css_first('a[href="/posts/form?kind=clinician_opening"]') is not None


async def test_home_page_no_post_actions_for_no_claim_user(
    authenticated_client: AsyncClient,
):
    """A no-claim user gets the My posts section but no active toolbar CTAs.
    The empty-state create button is disabled (locked_action) instead of a
    live link. No finish-setup card is rendered — the chrome
    `#onboarding-banner` is the single nudge."""
    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first('a[href="/posts/form?kind=referral"]') is None
    assert "+ Post a referral" not in response.text
    assert tree.css_first("#finish-setup-card") is None
    # My posts section always renders
    assert "My posts" in response.text
    # Empty-state CTA is a disabled button, not a live link
    assert "No posts yet." in response.text
    assert tree.css_first("button[disabled]") is not None
    assert tree.css_first('a[href="/posts/form"]') is None


async def test_home_page_empty_my_posts_shows_locked_cta_when_unverified(
    authenticated_client: AsyncClient,
):
    """An unverified user with no posts sees a disabled Create a post button
    (locked_action pattern) rather than a live link."""
    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert "No posts yet." in response.text
    btn = tree.css_first("button[disabled]")
    assert btn is not None
    assert "Create a post" in btn.text()


async def test_home_page_empty_my_posts_shows_active_cta_when_verified(
    authenticated_client: AsyncClient,
    db_test_session_manager,
    logged_in_user,
):
    """A verified user with no posts sees a live Create a post link."""
    from tests.helpers import make_clinician_with_org

    clinician = make_clinician_with_org(owner_id=logged_in_user.id, npi="1234567890")
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = True
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert "No posts yet." in response.text
    assert tree.css_first('a[href="/posts/form"]') is not None
    assert tree.css_first("button[disabled]") is None


async def test_home_page_no_blur_element(authenticated_client: AsyncClient):
    """The blur wrapper (`feed-teaser-blur`) is removed regardless of
    verification state — anonymization is now server-side via `can_access_network`,
    not a CSS filter on the client."""
    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    assert "feed-teaser-blur" not in response.text


async def test_home_page_has_no_inline_feed_verify_notice(
    authenticated_client: AsyncClient,
    db_test_session_manager,
    logged_in_user,
):
    """The home network feed carries no inline verify notice, even for an
    unverified viewer with network posts. The single chrome
    `#onboarding-banner` is the only place that explains verification
    unlocks the full view — the old `feed-verify-notice` is gone."""
    from tests.helpers import create_test_user, make_referral_detail

    author = create_test_user(username="net-poster")
    post = Post(kind="referral", owner_id=author.id)
    post.referral_detail = make_referral_detail()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    assert "feed-verify-notice" not in response.text
    assert "Complete verification" not in response.text


async def test_home_page_shows_primary_nav(authenticated_client: AsyncClient):
    """The home page passes current_user so is_authenticated=True and the
    primary nav links (Home, Posts, Profile, Sign out) render."""
    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    nav = tree.css_first('nav[aria-label="Primary"]')
    assert nav is not None
    links = {a.attributes.get("href") for a in nav.css("a")}
    assert "/home" in links
    assert "/posts" in links


# --- lifespan -----------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_skips_scheduler_entirely_when_disabled(monkeypatch):
    monkeypatch.setenv("DISABLE_SCHEDULER", "1")

    with (
        patch("src.main.check_database_health", new=AsyncMock()),
        patch("src.main.make_scheduler") as mk,
        patch("src.main.register_jobs") as reg,
    ):
        async with lifespan(FastAPI()):
            pass

        mk.assert_not_called()
        reg.assert_not_called()


@pytest.mark.asyncio
async def test_lifespan_starts_scheduler_when_enabled(monkeypatch):
    monkeypatch.delenv("DISABLE_SCHEDULER", raising=False)
    scheduler = MagicMock()

    with (
        patch("src.main.check_database_health", new=AsyncMock()),
        patch("src.main.make_scheduler", return_value=scheduler) as mk,
        patch("src.main.register_jobs") as reg,
    ):
        async with lifespan(FastAPI()):
            pass

        mk.assert_called_once()
        reg.assert_called_once_with(scheduler)
        scheduler.start.assert_called_once()
        scheduler.shutdown.assert_called_once_with(wait=False)
