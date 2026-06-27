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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import User
from src.main import lifespan
from tests.helpers import make_clinician_with_org

pytestmark = pytest.mark.asyncio


# --- Landing: `/` redirects to `/home`, the auth-aware hub --------------
#
# `/home` is the canonical home URL. `/` is a bare redirect to it for both
# auth states, so the brand link, bookmarks, and the bare domain all land
# in one place. `/home` then splits: a signed-in viewer gets the
# goal-oriented hub (`home.html`); an anonymous one gets the public
# landing page (`landing.html`), never the login wall.


@pytest.mark.parametrize("authed", [True, False])
async def test_root_redirects_to_home(
    authed: bool,
    authenticated_client: AsyncClient,
    test_client: AsyncClient,
):
    """`/` redirects to `/home` for both signed-in and anonymous visitors
    — `/home` is the single canonical home URL."""
    client = authenticated_client if authed else test_client
    response = await client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/home"


async def test_authenticated_home_renders_quicklinks(
    authenticated_client: AsyncClient,
):
    """An authenticated viewer hitting `/home` gets the goal hub — NOT a
    redirect. It renders the intent CTAs as three columns of plain links
    (Refer a patient / Find your next client / Manage), and (because a
    fresh account can't post yet) surfaces the dynamic `#home-setup` task
    at the top."""
    response = await authenticated_client.get("/home", follow_redirects=False)
    assert response.status_code == 200
    body = response.text
    for href in (
        # Refer a patient
        "/posts/form?kind=referral",
        "/posts?kind=clinician_opening",
        # Find your next client
        "/posts/form?kind=clinician_opening",
        "/posts?kind=referral",
        # Manage
        "/posts?owner=me",
        "/clinicians?owner=me",
        "/users/me",
    ):
        assert f'href="{href}"' in body, f"home goal hub missing a link to {href}"
    # A fresh account isn't post-ready, so the setup task is surfaced.
    assert 'id="home-setup"' in body, "setup task must show when the viewer can't post"
    # No network access yet → the greeting is "Welcome.", not "Welcome back."
    assert (
        HTMLParser(body).css_first("h1").text(strip=True) == "Welcome."
    ), "teased viewer must be greeted with Welcome."


async def test_authenticated_home_greets_returning_provider(
    superuser_client: AsyncClient,
):
    """A viewer with network access (`can_act_as_provider`, here via the
    superuser grant) is greeted with the returning-provider header."""
    response = await superuser_client.get("/home", follow_redirects=False)
    assert response.status_code == 200
    assert HTMLParser(response.text).css_first("h1").text(strip=True) == "Welcome back."


async def test_authenticated_home_hides_setup_task_when_post_ready(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The dynamic `#home-setup` task disappears once the viewer can post —
    here, a verified email plus a verified clinician profile (Claim A)."""
    async with db_test_session_manager() as session:
        async with session.begin():
            user = await session.get(User, logged_in_user.id)
            user.is_verified = True
            session.add(
                make_clinician_with_org(
                    owner_id=logged_in_user.id, clinician_verified=True
                )
            )

    response = await authenticated_client.get("/home", follow_redirects=False)
    assert response.status_code == 200
    assert (
        'id="home-setup"' not in response.text
    ), "setup task must be hidden once the viewer can post"


async def test_anonymous_home_renders_public_landing(
    test_client: AsyncClient,
):
    """An anonymous visitor hitting `/home` gets the public landing page
    (not the login wall) — the goal hub is signed-in only, so anonymous
    falls through to `landing.html`."""
    response = await test_client.get(
        "/home",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "/auth/login" not in response.headers.get("location", "")


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
