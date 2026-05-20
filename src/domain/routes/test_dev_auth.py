"""Tests for the dev-only auto-login route.

Two layers of guarding:

  1. ``mount_dev_routes`` only registers the router when the
     ``environment`` argument is ``"development"``. Tested with a
     fresh ``FastAPI()`` instance per case so the global
     ``src.main:app`` isn't mutated.
  2. The handler additionally raises 404 if
     ``settings.ENVIRONMENT`` doesn't read ``"development"`` at
     request time (defense in depth).

The happy-path test goes through the test client's already-mounted
``app`` (which runs with ``ENVIRONMENT="development"`` via
``.env.test``) and pins the contract a Playwright agent or a manual
bookmark relies on: 302 + ``Location: /`` + ``Set-Cookie:
fastapiusersauth=...``. The handler redirects to ``/`` so the root
handler (``src/main.py:read_root``) owns the choice of landing page;
this route only proves the cookie was issued.
"""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.auth_config import get_user_manager
from src.domain.logic.users.schema import UserCreate
from src.domain.routes import dev_auth
from src.framework.config import settings
from tests.fixtures import create_test_user

# --- mount_dev_routes: env-gated router registration --------------------


def test_mount_dev_routes_registers_when_environment_is_development():
    """A fresh app + `mount_dev_routes(env="development")` produces a
    `/dev/login-as-seed-user` route on `app.routes`. Pins the dev-
    mode mount."""
    app = FastAPI()
    dev_auth.mount_dev_routes(app, environment="development")
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/dev/login-as-seed-user" in paths


def test_mount_dev_routes_skips_when_environment_is_production():
    """The production mount path MUST NOT register the dev route.
    This is the canary against an accidental env-flag flip leaking the
    auto-login backdoor into prod."""
    app = FastAPI()
    dev_auth.mount_dev_routes(app, environment="production")
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/dev/login-as-seed-user" not in paths


def test_mount_dev_routes_skips_when_environment_is_arbitrary_other():
    """Any non-`development` value (staging, test, empty string, etc.)
    is treated as "not dev" — the mount is strict-equality, not a
    truthy/falsy check."""
    app = FastAPI()
    for env in ("staging", "test", "PRODUCTION", "Development", ""):
        dev_auth.mount_dev_routes(app, environment=env)
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/dev/login-as-seed-user" not in paths


# --- Handler: happy path ------------------------------------------------


async def test_dev_login_issues_session_cookie_and_redirects(
    test_client: AsyncClient,
    test_app: FastAPI,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
):
    """Hitting the route with a seed user in the DB issues the same
    `fastapiusersauth` cookie a production login would, and 302s to
    `/` (root then forwards to the actual landing page). This is the
    contract a Playwright MCP agent's first-tool-call relies on."""
    # Seed the DEV_LOGIN_EMAIL user. Use the standard fastapi-users
    # user-manager dependency so the password is hashed correctly.
    seed_email = "dev-login-seed@example.com"
    monkeypatch.setattr(settings, "DEV_LOGIN_EMAIL", seed_email)
    user_data = UserCreate(email=seed_email, password="anything", username="dev-seed")
    await create_test_user(db_test_session_manager, user_data, get_user_manager)

    response = await test_client.get("/dev/login-as-seed-user", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    set_cookie = response.headers.get("Set-Cookie", "")
    assert "fastapiusersauth=" in set_cookie, (
        "expected the session cookie to be set on the response — "
        "fastapi-users' CookieTransport.login() puts it on Set-Cookie"
    )


async def test_dev_login_404s_when_seed_user_missing(
    test_client: AsyncClient,
    test_app: FastAPI,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
):
    """If `DEV_LOGIN_EMAIL` points at a user that doesn't exist (no
    seed yet), the route 404s with a hint to run `dev seed` rather
    than crashing or silently authenticating as a non-user."""
    monkeypatch.setattr(
        settings, "DEV_LOGIN_EMAIL", "nobody-at-this-address@example.com"
    )
    response = await test_client.get("/dev/login-as-seed-user", follow_redirects=False)
    assert response.status_code == 404
    assert "dev seed" in response.text


async def test_dev_login_404s_when_environment_is_not_development(
    test_client: AsyncClient,
    test_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
):
    """In-handler defense-in-depth: even if the route is mounted (it
    is in the test app, which runs with `ENVIRONMENT=development`), a
    request-time check against the live setting 404s when the env
    flag isn't `"development"`. Belt-and-suspenders against a future
    code path that toggles the env at runtime."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    response = await test_client.get("/dev/login-as-seed-user", follow_redirects=False)
    assert response.status_code == 404
