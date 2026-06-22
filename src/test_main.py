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

from src.main import lifespan

pytestmark = pytest.mark.asyncio


# --- Landing: `/` and `/home` resolve to browse --------------------------
#
# `/posts` is the authenticated landing surface (I3). The bespoke `/home`
# dashboard template was retired: "My posts" folds into `/posts?owner=me`
# (nav avatar menu) and "Recent in the network" *is* the default
# newest-first browse feed. `/home` is kept only as an alias of `/` so the
# anonymous brand link and stale bookmarks keep resolving — both routes
# redirect an authenticated viewer to `/posts` and render the public
# landing page for an anonymous one.


@pytest.mark.parametrize("path", ["/", "/home"])
async def test_authenticated_landing_redirects_to_browse(
    path: str,
    authenticated_client: AsyncClient,
):
    """An authenticated viewer hitting `/` or `/home` is redirected to the
    `/posts` browse feed — the default landing surface. No `?kind=` bias is
    applied; the unfiltered feed lists every kind newest-first."""
    response = await authenticated_client.get(path, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/posts"


@pytest.mark.parametrize("path", ["/", "/home"])
async def test_anonymous_landing_renders_public_page(
    path: str,
    test_client: AsyncClient,
):
    """An anonymous visitor hitting `/` or `/home` gets the public landing
    page (not the login wall) — `/home` is a plain alias of `/`."""
    response = await test_client.get(
        path,
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
