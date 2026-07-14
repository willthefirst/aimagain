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

from src.domain.routes.dev import dev_components
from src.framework.config import settings

# --- mount_dev_components: env-gated router registration ------------------


def _mounted_paths(app: FastAPI) -> set[str | None]:
    """Collect registered paths, flattening fastapi >=0.137's
    ``_IncludedRouter`` markers. See `test_dev_auth._mounted_paths` for
    the rationale — duplicated rather than imported so this test file
    keeps no cross-file dependency on a sibling under `src/`.
    """
    out: set[str | None] = set()
    stack: list[object] = list(getattr(app, "routes", []) or [])
    while stack:
        route = stack.pop()
        original = getattr(route, "original_router", None)
        if original is not None:
            stack.extend(getattr(original, "routes", []) or [])
        else:
            out.add(getattr(route, "path", None))
    return out


def test_mount_registers_when_environment_is_development():
    app = FastAPI()
    dev_components.mount_dev_components(app, environment="development")
    paths = _mounted_paths(app)
    assert "/dev/components" in paths


def test_mount_skips_when_environment_is_production():
    app = FastAPI()
    dev_components.mount_dev_components(app, environment="production")
    paths = _mounted_paths(app)
    assert "/dev/components" not in paths


def test_mount_skips_when_environment_is_arbitrary_other():
    app = FastAPI()
    for env in ("staging", "test", "DEVELOPMENT", ""):
        dev_components.mount_dev_components(app, environment=env)
    paths = _mounted_paths(app)
    assert "/dev/components" not in paths


# --- Handler ---------------------------------------------------------------


async def test_component_gallery_returns_html(test_client: AsyncClient):
    response = await test_client.get("/dev/components")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


async def test_component_gallery_documents_picker(test_client: AsyncClient):
    """The gallery renders the shared `picker()` macro so the
    choose-your-path card grid can be iterated in isolation."""
    response = await test_client.get("/dev/components")
    assert 'id="picker"' in response.text


async def test_component_gallery_documents_conditional_field(
    test_client: AsyncClient,
):
    """The gallery renders the `conditional_field()` reveal wrapper
    (inside a `<form>`, using a real referral token) so the pure-CSS
    reveal pattern can be inspected in isolation."""
    response = await test_client.get("/dev/components")
    assert 'id="conditional-field"' in response.text
    assert 'data-reveal-when="insurance_carriers:other"' in response.text


async def test_component_gallery_404s_when_not_development(
    test_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    response = await test_client.get("/dev/components")
    assert response.status_code == 404
