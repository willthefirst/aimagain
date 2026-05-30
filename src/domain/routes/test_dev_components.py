"""Tests for the dev-only component gallery route.

Two layers of guarding apply:

  1. ``mount_dev_components`` only registers the router when the
     ``environment`` argument is ``"development"``. Tested with a
     fresh ``FastAPI()`` instance per case.
  2. Each handler raises 404 if ``settings.ENVIRONMENT`` doesn't read
     ``"development"`` at request time (defense in depth).

Happy-path test confirms 200 + HTML via the already-mounted test ``app``
(which runs with ``ENVIRONMENT="development"`` via ``.env.test``).
"""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from src.domain.routes import dev_components
from src.framework.config import settings

# --- mount_dev_components: env-gated router registration ------------------


def test_mount_registers_when_environment_is_development():
    app = FastAPI()
    dev_components.mount_dev_components(app, environment="development")
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/dev/components" in paths


def test_mount_skips_when_environment_is_production():
    app = FastAPI()
    dev_components.mount_dev_components(app, environment="production")
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/dev/components" not in paths


def test_mount_skips_when_environment_is_arbitrary_other():
    app = FastAPI()
    for env in ("staging", "test", "DEVELOPMENT", ""):
        dev_components.mount_dev_components(app, environment=env)
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/dev/components" not in paths


# --- Handler ---------------------------------------------------------------


async def test_component_gallery_returns_html(test_client: AsyncClient):
    response = await test_client.get("/dev/components")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


async def test_component_gallery_404s_when_not_development(
    test_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    response = await test_client.get("/dev/components")
    assert response.status_code == 404
