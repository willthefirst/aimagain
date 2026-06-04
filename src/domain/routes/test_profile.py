"""Integration tests for the Profile Hub bespoke route.

Confirms the page renders for an authenticated user, the mode dispatch
flows through to the right partial, and the route is admin-free (any
active user can see their own hub — Claim B coordinators must be able
to use it without holding Claim A).

The `/profile/identity` step is a *dispatching picker* (issue #1166): its
two cards link out to the canonical `/clinicians/form` and
`/organizations/form`. It hosts no create form of its own; the bespoke
`POST /profile/clinician|org|.../identity|.../license` endpoints were
removed in favor of the canonical creates.
"""

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import Clinician, User

pytestmark = pytest.mark.asyncio


async def test_profile_hub_links_identity_row_to_step_subroute(
    authenticated_client: AsyncClient,
):
    """A fresh dev user (no clinician, no org representation) lands on the
    `/profile` table of contents. The hub is a pure index now: the identity
    row is an incomplete link to the `/profile/identity` step subroute, not
    an embedded persona chooser."""
    response = await authenticated_client.get("/profile")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    # The hub is a TOC — the dispatching picker lives on the step page.
    assert "I&#39;m a clinician" not in response.text
    identity_row = HTMLParser(response.text).css_first(
        '#onboarding-checklist [data-step="identity"]'
    )
    assert identity_row is not None
    assert identity_row.css_first(".picker") is None
    link = identity_row.css_first("a.onboarding-progress-link")
    assert link is not None
    assert link.attributes.get("href") == "/profile/identity"


async def test_profile_identity_step_renders_dispatching_picker(
    authenticated_client: AsyncClient,
):
    """`/profile/identity` is a dispatching picker: two cards linking OUT to
    the canonical create forms. It carries no `?path=` selector and hosts no
    inline create form."""
    response = await authenticated_client.get("/profile/identity")
    assert response.status_code == 200
    # The two persona cards, rendered as the shared picker grid.
    assert "I&#39;m a clinician" in response.text
    assert "I represent an organization" in response.text
    assert 'class="picker"' in response.text
    assert 'class="picker-option"' in response.text
    # Cards dispatch to the canonical create forms (via entity_form_url),
    # not the retired `?path=` selector or inline forms.
    assert 'href="/clinicians/form"' in response.text
    assert 'href="/organizations/form"' in response.text
    assert "?path=" not in response.text
    # No inline create form is hosted here anymore (read xor form).
    assert "Verify your NPI" not in response.text


async def test_profile_identity_step_shows_started_clinician_with_manage_link(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """When the user has already created a clinician, the dispatching picker
    also surfaces a read-only posture row linking to the clinician's own
    canonical page (where NPI re-verify / license attestation live)."""
    from tests.helpers import make_clinician_with_org

    clinician = make_clinician_with_org(
        owner_id=logged_in_user.id,
        npi="1234567890",
        npi_match_status="pending",
    )
    clinician.clinician_verified = False
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/profile/identity")
    assert response.status_code == 200
    # Static template text isn't HTML-escaped (only `{{ }}` vars are), so the
    # apostrophe renders literally.
    assert "What you've started" in response.text
    # Posture row links to the canonical clinician edit page, not a bespoke
    # profile sub-form.
    assert f'href="/clinicians/{clinician.id}/form"' in response.text


async def test_profile_step_unknown_key_returns_404(
    authenticated_client: AsyncClient,
):
    """`/profile/<unknown>` is not a registered onboarding step, so the
    step handler 404s rather than rendering an empty page."""
    response = await authenticated_client.get("/profile/not-a-step")
    assert response.status_code == 404


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


async def test_profile_hub_add_claim_mode_renders_unlocks_unchanged(
    authenticated_client: AsyncClient,
    db_test_session_manager,
    logged_in_user,
):
    """A verified user with `?intent=add_claim` lands in `add-a-claim`
    mode — wireframe-L6 "Unlocks / Unchanged" framing."""
    from tests.helpers import make_clinician_with_org

    clinician = make_clinician_with_org(owner_id=logged_in_user.id, npi="1234567890")
    # `make_clinician_with_org` defaults to clinician_verified=True; that's
    # exactly what the test needs here.
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/profile?intent=add_claim")
    assert response.status_code == 200
    # Distinctive copy from `_add_claim.html`.
    assert "Add a capability" in response.text
    assert "Unlocks" in response.text
    assert "Unchanged" in response.text


async def test_post_profile_clinician_details_update_saves_location(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """POST /profile/clinician/{id}/details patches location fields and
    returns HX-Redirect: /profile."""
    from tests.helpers import make_clinician_with_org

    clinician = make_clinician_with_org(
        owner_id=logged_in_user.id,
        npi="1234567890",
        location_city=None,
        location_state=None,
        location_zip=None,
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
    clinician_id = clinician.id

    response = await authenticated_client.post(
        f"/profile/clinician/{clinician_id}/details",
        data={
            "location_city": "Portland",
            "location_state": "OR",
            "location_zip": "97201",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("HX-Redirect") == "/profile"

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(Clinician).where(Clinician.id == clinician_id)
        )
        updated = result.scalars().first()
        assert updated.location_city == "Portland"
        assert updated.location_state == "OR"
        assert updated.location_zip == "97201"


async def test_post_profile_clinician_details_update_rejects_wrong_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A user cannot update another user's clinician details."""
    from tests.helpers import create_test_user, make_clinician_with_org

    other = create_test_user(username="other-details")
    clinician = make_clinician_with_org(owner_id=other.id, npi="5555555555")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(clinician)

    response = await authenticated_client.post(
        f"/profile/clinician/{clinician.id}/details",
        data={"location_city": "Evil", "location_state": "CA", "location_zip": "90210"},
        follow_redirects=False,
    )
    assert response.status_code == 403
