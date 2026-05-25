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


async def test_home_page_shows_post_buttons(authenticated_client: AsyncClient):
    """The home page renders both action buttons linking to the correct
    create-form URLs."""
    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first('a[href="/referrals/form"]') is not None
    assert tree.css_first('a[href="/openings/form"]') is not None


async def test_home_page_shows_primary_nav(authenticated_client: AsyncClient):
    """The home page passes current_user so is_authenticated=True and the
    primary nav links (Home, Referrals, Openings, Profile, Sign out) render."""
    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    nav = tree.css_first('nav[aria-label="Primary"]')
    assert nav is not None
    links = {a.attributes.get("href") for a in nav.css("a")}
    assert "/home" in links
    assert "/referrals" in links
    assert "/openings" in links


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
