"""Integration tests for the `/users/me/access` bespoke route.

Covers:
  - Unauthenticated requests are redirected / denied.
  - Authenticated requests to the index render the access overview.
  - Authenticated requests to /capabilities list all capabilities.
  - Authenticated requests to a capability detail return 200 with tree.
  - Unknown capability names return 404.
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_access_index_unauthenticated_redirected(test_client: AsyncClient):
    """Unauthenticated GET /users/me/access is bounced — not 200."""
    response = await test_client.get("/users/me/access", follow_redirects=False)
    assert response.status_code != 200


async def test_access_index_authenticated_returns_200(
    authenticated_client: AsyncClient,
):
    """Authenticated GET /users/me/access renders the access overview with a
    link to the capabilities list."""
    response = await authenticated_client.get("/users/me/access")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Capabilities" in response.text
    assert "/users/me/access/capabilities" in response.text


async def test_capabilities_index_unauthenticated_redirected(test_client: AsyncClient):
    """Unauthenticated GET /users/me/access/capabilities is bounced."""
    response = await test_client.get(
        "/users/me/access/capabilities", follow_redirects=False
    )
    assert response.status_code != 200


async def test_capabilities_index_authenticated_returns_200(
    authenticated_client: AsyncClient,
):
    """Authenticated GET /users/me/access/capabilities lists all capabilities."""
    response = await authenticated_client.get("/users/me/access/capabilities")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "provider-network" in response.text


async def test_capabilities_index_shows_granted_or_denied(
    authenticated_client: AsyncClient,
):
    """The capabilities list surfaces a granted/denied label for each capability."""
    response = await authenticated_client.get("/users/me/access/capabilities")
    assert response.status_code == 200
    assert "Available" in response.text or "Not available yet" in response.text


async def test_capability_detail_network_returns_200(
    authenticated_client: AsyncClient,
):
    """GET /users/me/access/capabilities/provider-network renders the requirement tree."""
    response = await authenticated_client.get(
        "/users/me/access/capabilities/provider-network"
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    # Capability label_active appears in the page heading and breadcrumb.
    assert "Provider network" in response.text
    # Tree node labels appear — active form for unmet, done form for met.
    assert "Verify your email" in response.text or "Email verified" in response.text
    assert (
        "Verify a clinician" in response.text or "Clinician verified" in response.text
    )
    assert (
        "Verify your organization" in response.text
        or "Organization verified" in response.text
    )


async def test_capability_detail_shows_status(
    authenticated_client: AsyncClient,
):
    """The detail page shows an available/locked badge."""
    response = await authenticated_client.get(
        "/users/me/access/capabilities/provider-network"
    )
    assert response.status_code == 200
    assert "Available" in response.text or "Not available yet" in response.text


async def test_capability_detail_nonexistent_returns_404(
    authenticated_client: AsyncClient,
):
    """GET /users/me/access/capabilities/<unknown> returns 404."""
    response = await authenticated_client.get(
        "/users/me/access/capabilities/nonexistent"
    )
    assert response.status_code == 404


async def test_capability_detail_unauthenticated_redirected(test_client: AsyncClient):
    """Unauthenticated GET /users/me/access/capabilities/provider-network is bounced."""
    response = await test_client.get(
        "/users/me/access/capabilities/provider-network",
        follow_redirects=False,
    )
    assert response.status_code != 200


async def test_capabilities_index_superuser_shows_bypass_label(
    superuser_client: AsyncClient,
):
    """Superusers see 'Available (superuser)' on the capabilities list."""
    response = await superuser_client.get("/users/me/access/capabilities")
    assert response.status_code == 200
    assert "Available (superuser)" in response.text


async def test_capability_detail_superuser_shows_bypass_note(
    superuser_client: AsyncClient,
):
    """Superusers see a bypass note on the capability detail page."""
    response = await superuser_client.get(
        "/users/me/access/capabilities/provider-network"
    )
    assert response.status_code == 200
    assert "Superuser" in response.text
    assert "Available" in response.text
