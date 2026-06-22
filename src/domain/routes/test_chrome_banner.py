"""Pins the verification status and chrome banner contract.

The global chrome carries one chrome signal (`#onboarding-banner`, copy in
`base.html`, gated on `needs_provider_entity` from `base_context`). It is a
derived gate (`RESOURCE_GRAMMAR.md` §"Derived gates"): shown only when an
authenticated account holds neither a clinician profile nor an org rep — so
no post can be authored yet — and it dispatches into the two minimal create
forms (`/clinicians/form`, `/organizations/form`). The old `/profile` hub has
been removed; the verification card on `/users/me` is the new home for claim
setup links.

Browse (`/posts`) is the authenticated landing surface (I3) — the bespoke
`/home` dashboard was retired — so these tests exercise the chrome on
`/posts`. They assert:

1. The global `#onboarding-banner` is shown for an empty (no clinician/org)
   account and links to both minimal create forms; it goes silent once the
   account holds a provider entity (verified or not), and it renders inside
   the page `<main>` band.
2. The authenticated primary nav renders the redesigned shape end-to-end
   (through the real entity registry, not the template-test stubs): brand →
   posts collection, a prominent `+ Post` button → the post create form, and
   the avatar menu's My posts / Account / Sign out items. Structure is pinned
   at the template level in `framework/templates/test_page_header.py`; this
   route test pins that the live URL helpers resolve to the expected paths.
"""

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser

from tests.helpers import (  # noqa: F401  (kept available for future tests)
    promote_to_admin,
)

pytestmark = pytest.mark.asyncio


async def test_onboarding_banner_shown_for_empty_account(
    authenticated_client: AsyncClient,
):
    """A fresh account (no clinician profile, no org rep) sees the global
    `#onboarding-banner` nudging it to add a provider entity. The old
    per-page finish-setup card is gone — the banner is the single nudge."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("#finish-setup-card") is None
    assert "Open Profile" not in response.text
    banner = tree.css_first("#onboarding-banner")
    assert banner is not None
    assert "start posting" in banner.text()


async def test_onboarding_banner_links_to_both_minimal_create_forms(
    authenticated_client: AsyncClient,
):
    """The banner is a derived gate, not a wizard: it dispatches into the two
    existing minimal create forms (`/clinicians/form`, `/organizations/form`)."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    banner = HTMLParser(response.text).css_first("#onboarding-banner")
    assert banner is not None
    hrefs = {a.attributes.get("href") for a in banner.css("a")}
    assert "/clinicians/form" in hrefs
    assert "/organizations/form" in hrefs


async def test_onboarding_banner_renders_inside_main(
    authenticated_client: AsyncClient,
):
    """The banner lives inside the page `<main>` band (not the header)."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    banner = tree.css_first("main #onboarding-banner")
    assert banner is not None


async def test_onboarding_banner_hidden_once_clinician_added(
    authenticated_client: AsyncClient,
    db_test_session_manager,
    logged_in_user,
):
    """The banner keys on entity existence, not verification: once the account
    holds a clinician profile (even an unverified one) the global banner is
    silent — the residual verify-to-post step lives on `/users/me`."""
    from tests.helpers import make_clinician_with_org

    clinician = make_clinician_with_org(owner_id=logged_in_user.id, npi="1234567890")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    assert HTMLParser(response.text).css_first("#onboarding-banner") is None


async def test_onboarding_banner_hidden_for_org_rep(
    authenticated_client: AsyncClient,
    db_test_session_manager,
    logged_in_user,
):
    """An account that holds an org representation (no clinician) also clears
    the banner — "clinician OR org" satisfies the derived gate."""
    from src.domain.models.org_representations.org_representation import (
        OrgRepresentation,
    )
    from tests.helpers import make_organization_row

    org = make_organization_row(owner_id=logged_in_user.id)
    rep = OrgRepresentation(
        user_id=logged_in_user.id,
        org_id=org.id,
        role="coordinator",
        authority_method="admin_review",
        authority_status="verified",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(org)
            session.add(rep)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    assert HTMLParser(response.text).css_first("#onboarding-banner") is None


async def test_authenticated_primary_nav_redesign(authenticated_client: AsyncClient):
    """End-to-end (through the real entity registry) the authenticated nav is
    the canonical Pico shape: brand → posts collection, a plain `Post` link →
    the post create form, and a Pico `<details class="dropdown">` profile menu
    with My posts / Account / Sign out. "Saved" is deferred and must not appear.
    Anonymous nav stays brand-only — pinned in
    `framework/templates/test_views.py`."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    nav = HTMLParser(response.text).css_first('nav[aria-label="Primary"]')
    assert nav is not None

    # Brand → posts collection (Browse is the default landing surface).
    brand = nav.css_first("a strong")
    assert brand is not None and brand.text(strip=True) == "Bedlam Connect"
    assert brand.parent.attributes.get("href") == "/posts"

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
