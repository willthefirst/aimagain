"""Pins the authenticated primary-nav contract end-to-end.

`/` now redirects to the signed-in `/home` hub, so this test exercises the
chrome on `/posts` (a representative authenticated app page): the authenticated
primary nav renders the redesigned shape end-to-end (through the real entity
registry, not the template-test stubs) — brand → posts collection, a prominent
`Post` link → the post create form, and the avatar menu's My posts / Account /
Sign out items. Structure is pinned at the template level in
`framework/templates/test_page_header.py`; this route test pins that the live
URL helpers resolve to the expected paths.
"""

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser

from tests.helpers import (  # noqa: F401  (kept available for future tests)
    promote_to_admin,
)

pytestmark = pytest.mark.asyncio


async def test_authenticated_primary_nav_redesign(authenticated_client: AsyncClient):
    """End-to-end (through the real entity registry) the authenticated nav is
    the canonical Pico shape: brand → `/home`, a plain `Post` link →
    the post create form, and a Pico `<details class="dropdown">` profile menu
    with My posts / Account / Sign out. "Saved" is deferred and must not appear.
    Anonymous nav stays brand-only — pinned in
    `framework/templates/test_views.py`."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    nav = HTMLParser(response.text).css_first('nav[aria-label="Primary"]')
    assert nav is not None

    # Brand → /home (the quicklinks hub).
    brand = nav.css_first("a strong")
    assert brand is not None and brand.text(strip=True) == "Bedlam Connect"
    assert brand.parent.attributes.get("href") == "/home"

    # `Post` is a plain link (no `role=button`, no `+`) → the post create form.
    posts = [a for a in nav.css("a") if a.text(strip=True) == "Post"]
    assert len(posts) == 1
    assert posts[0].attributes.get("href") == "/posts/form"
    assert posts[0].attributes.get("role") is None

    # Profile dropdown items.
    menu = nav.css_first("details.dropdown#nav-menu")
    assert menu is not None
    items = {a.text(strip=True): a for a in menu.css("ul li a")}
    assert set(items) == {"My posts", "Account", "Sign out"}
    assert "Saved" not in items
    assert items["My posts"].attributes.get("href") == "/posts?owner=me"
    assert items["Account"].attributes.get("href") == "/users/me"
    assert items["Sign out"].attributes.get("hx-post") == "/auth/sign-out"
