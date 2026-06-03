"""Integration tests for the Profile Hub bespoke route.

Confirms the page renders for an authenticated user, the mode dispatch
flows through to the right partial, and the route is admin-free (any
active user can see their own hub — Claim B coordinators must be able
to use it without holding Claim A).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import Clinician, ClinicianLicensure, User

pytestmark = pytest.mark.asyncio


async def test_profile_hub_renders_persona_chooser_for_new_user(
    authenticated_client: AsyncClient,
):
    """A fresh dev user (no clinician, no org representation) and no
    `?path=` hint lands in setup mode showing the persona chooser — not
    either onboarding sub-flow yet."""
    response = await authenticated_client.get("/profile")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    # The two persona cards from the chooser branch of `_setup.html`.
    # Jinja HTML-escapes the apostrophe, so match the rendered form.
    assert "I&#39;m a clinician" in response.text
    assert "I represent an organization" in response.text
    assert "?path=clinician" in response.text
    assert "?path=org" in response.text
    # The chooser renders as the shared picker card grid — each option is a
    # bordered `.picker-option` card, not a bare underlined link. This is the
    # primary action on the setup page, so it must read as a card.
    assert 'class="picker"' in response.text
    assert 'class="picker-option"' in response.text
    # Neither sub-flow's form is shown until a persona is picked.
    assert "Verify your NPI" not in response.text


async def test_profile_hub_clinician_path_shows_npi_flow(
    authenticated_client: AsyncClient,
):
    """`/profile?path=clinician` renders the clinician onboarding flow —
    NPI verification — and not the org-registration form."""
    response = await authenticated_client.get("/profile?path=clinician")
    assert response.status_code == 200
    assert "Verify your NPI" in response.text
    assert "Register an organization" not in response.text


async def test_profile_hub_org_path_shows_org_flow(
    authenticated_client: AsyncClient,
):
    """`/profile?path=org` renders the org-registration flow and not the
    clinician NPI form."""
    response = await authenticated_client.get("/profile?path=org")
    assert response.status_code == 200
    assert "Register an organization" in response.text
    assert "Verify your NPI" not in response.text


async def test_profile_hub_started_clinician_ignores_path_hint(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A user who already created a clinician resumes the clinician flow
    even with `?path=org` — the started path wins over the hint, so they
    aren't bounced back to the chooser or the wrong sub-flow."""
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

    response = await authenticated_client.get("/profile?path=org")
    assert response.status_code == 200
    assert "Verify your NPI" in response.text
    assert "I represent an organization" not in response.text


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


async def test_post_profile_clinician_creates_and_redirects(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """POST /profile/clinician creates a minimal clinician + fires NPI
    verification inline, then returns HX-Redirect: /profile."""
    response = await authenticated_client.post(
        "/profile/clinician",
        data={
            "first_name": "Jane",
            "last_name": "Smith",
            "npi": "1234567890",
            "location_city": "Portland",
            "location_state": "OR",
            "location_zip": "97201",
        },
    )

    assert response.status_code == 201
    assert response.headers.get("HX-Redirect") == "/profile"

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(Clinician).where(Clinician.owner_id == logged_in_user.id)
        )
        clinician = result.scalars().first()
        assert clinician is not None
        assert clinician.npi == "1234567890"
        assert clinician.org_id is not None


async def test_post_profile_clinician_without_location(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """POST /profile/clinician works without location fields — the fast
    path only needs name + NPI.  Location columns stay NULL on the
    affiliation row and can be filled in later via the details endpoint."""
    response = await authenticated_client.post(
        "/profile/clinician",
        data={
            "first_name": "Jane",
            "last_name": "Smith",
            "npi": "1234567890",
        },
    )

    assert response.status_code == 201
    assert response.headers.get("HX-Redirect") == "/profile"

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(Clinician).where(Clinician.owner_id == logged_in_user.id)
        )
        clinician = result.scalars().first()
        assert clinician is not None
        assert clinician.npi == "1234567890"
        assert clinician.location_city is None
        assert clinician.location_state is None


async def test_post_profile_clinician_requires_authentication(
    test_client: AsyncClient,
):
    """Unauthenticated POST to /profile/clinician is rejected."""
    response = await test_client.post(
        "/profile/clinician",
        data={
            "first_name": "Jane",
            "last_name": "Smith",
            "npi": "1234567890",
            "location_city": "Portland",
            "location_state": "OR",
            "location_zip": "97201",
        },
        follow_redirects=False,
    )
    assert response.status_code != 201


async def test_post_profile_clinician_license_creates_attests_and_redirects(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """POST /profile/clinician/{id}/license creates a licensure, attests
    it active in one step, and returns HX-Redirect: /profile."""
    from tests.helpers import make_clinician_with_org

    clinician = make_clinician_with_org(
        owner_id=logged_in_user.id,
        npi="1234567890",
        npi_match_status="matched",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
    clinician_id = clinician.id

    response = await authenticated_client.post(
        f"/profile/clinician/{clinician_id}/license",
        data={
            "license_type": "lcsw",
            "license_number": "LCS-99999",
            "issuing_state": "OR",
        },
    )

    assert response.status_code == 201
    assert response.headers.get("HX-Redirect") == "/profile"

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ClinicianLicensure).where(
                ClinicianLicensure.clinician_id == clinician_id
            )
        )
        licensure = result.scalars().first()
        assert licensure is not None
        assert licensure.attested_active is True
        assert licensure.status == "active"


async def test_post_profile_clinician_identity_update_retries_verification(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """POST /profile/clinician/{id}/identity updates name + NPI and
    re-runs verification inline, returning HX-Redirect: /profile."""
    from tests.helpers import make_clinician_with_org

    clinician = make_clinician_with_org(
        owner_id=logged_in_user.id,
        npi="1111111111",
        npi_match_status="mismatch",
    )
    clinician.clinician_verified = False
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
    clinician_id = clinician.id

    response = await authenticated_client.post(
        f"/profile/clinician/{clinician_id}/identity",
        data={
            "first_name": "Jane",
            "last_name": "Smith",
            "npi": "9999999999",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("HX-Redirect") == "/profile"

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(Clinician).where(Clinician.id == clinician_id)
        )
        updated = result.scalars().first()
        assert updated.npi == "9999999999"
        assert updated.first_name == "Jane"


async def test_post_profile_clinician_identity_update_rejects_wrong_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A user cannot update another user's clinician identity."""
    from tests.helpers import create_test_user, make_clinician_with_org

    other = create_test_user(username="other-identity")
    clinician = make_clinician_with_org(owner_id=other.id, npi="2222222222")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(clinician)

    response = await authenticated_client.post(
        f"/profile/clinician/{clinician.id}/identity",
        data={"first_name": "Evil", "last_name": "Hacker", "npi": "3333333333"},
        follow_redirects=False,
    )
    assert response.status_code == 403


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


async def test_post_profile_clinician_license_requires_authentication(
    test_client: AsyncClient,
):
    """Unauthenticated POST to /profile/clinician/{id}/license is rejected."""
    import uuid

    response = await test_client.post(
        f"/profile/clinician/{uuid.uuid4()}/license",
        data={
            "license_type": "lcsw",
            "license_number": "LCS-99999",
            "issuing_state": "OR",
        },
        follow_redirects=False,
    )
    assert response.status_code != 201


async def test_post_profile_clinician_license_rejects_wrong_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A user cannot add a license to another user's clinician."""
    from tests.helpers import create_test_user, make_clinician_with_org

    other = create_test_user(username="other-owner")
    clinician = make_clinician_with_org(owner_id=other.id, npi="9999999999")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(clinician)
    clinician_id = clinician.id

    response = await authenticated_client.post(
        f"/profile/clinician/{clinician_id}/license",
        data={
            "license_type": "lcsw",
            "license_number": "LCS-STOLEN",
            "issuing_state": "CA",
        },
        follow_redirects=False,
    )
    assert response.status_code == 403
