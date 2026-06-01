"""Integration tests for the Profile Hub bespoke route.

Confirms the page renders for an authenticated user, the mode dispatch
flows through to the right partial, and the route is admin-free (any
active user can see their own hub — Claim B coordinators must be able
to use it without holding Claim A).
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_profile_hub_renders_setup_for_new_user(
    authenticated_client: AsyncClient,
):
    """A fresh dev user (no clinician, no org representation) lands in
    setup mode — the wireframe-L1 goal picker."""
    response = await authenticated_client.get("/profile")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    # Setup mode's distinctive copy from `_setup.html`.
    assert "What do you want to do on Bedlam Connect" in response.text
    # Both cards render (Claim A + Claim B); the Claim A card has
    # the "+ Add a clinician profile" CTA when none exists yet.
    assert (
        "Refer &amp; take clients" in response.text
        or "Refer & take clients" in response.text
    )
    assert "Post on behalf of an organization" in response.text


async def test_profile_hub_requires_authentication(test_client: AsyncClient):
    """Unauthenticated requests get the framework's auth bounce — no
    302/401 contract assertion beyond "not 200" because the auth
    middleware's exact response shape isn't this test's concern."""
    response = await test_client.get("/profile", follow_redirects=False)
    assert response.status_code != 200


async def test_profile_hub_in_navigation(authenticated_client: AsyncClient):
    """The base.html nav points the Profile tab at `/profile` (not
    `/users/me`). Pin the nav href so a refactor doesn't silently re-
    route the chrome."""
    response = await authenticated_client.get("/home")
    assert response.status_code == 200
    # The Profile link target should be the bespoke hub.
    assert 'href="/profile"' in response.text
