"""Route-level tests for the /welcome onboarding wizard.

Covers:
- GET /welcome dispatches to next_step (redirect to / for no intent, /welcome/verify for no clinician)
- GET /welcome/verify renders with 200 and the step header
- POST /welcome/verify happy path: creates Provider+Licensure, runs verification, redirects
- POST /welcome/verify validation error: re-renders form with 422 inline errors
- GET /welcome/first-opening renders when preconditions met
- GET /welcome/first-opening redirects to /welcome when no clinician
- POST /welcome/first-opening happy path: Opening created, redirects to /welcome/done
- POST /welcome/first-opening validation error: re-renders form with errors
- POST /welcome/first-opening skip-note: colleague_note is None
- GET /welcome/done renders static peer cards
- GET /welcome/coming-soon renders placeholder
- Unauthenticated access redirects to login

NPPES is stubbed via `BEDLAM_VERIFY_DEV_FALLBACK=1`; OIG uses the local LEIE fixture.
"""

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.verifications import oig as oig_module
from src.domain.models import OpeningDetail, Provider, User
from src.domain.models.posts.post import Post

pytestmark = pytest.mark.asyncio

_LEIE_FIXTURE = (
    Path(__file__).parent.parent
    / "logic"
    / "verifications"
    / "test_data"
    / "leie_sample.csv"
)

_VALID_BODY = {
    "first_name": "Jane",
    "last_name": "Smith",
    "work_email": "jane@clinic.example",
    "license_type": "lcsw",
    "license_number": "L-99999",
    "issuing_state": "IL",
}


@pytest.fixture(autouse=True)
def _stub_external(monkeypatch):
    """Point OIG at the local fixture; enable dev-mode NPPES fallback."""
    monkeypatch.setenv("LEIE_CSV_PATH", str(_LEIE_FIXTURE))
    monkeypatch.setenv("BEDLAM_VERIFY_DEV_FALLBACK", "1")
    oig_module._reset_cache_for_tests()
    yield
    oig_module._reset_cache_for_tests()


async def _set_intent(
    session_maker: async_sessionmaker[AsyncSession],
    user_email: str,
    intent: str,
) -> None:
    async with session_maker() as session:
        async with session.begin():
            result = await session.execute(
                select(User).filter(User.email == user_email)
            )
            user = result.scalars().first()
            assert user is not None
            user.onboarding_intent = intent


# ---------------------------------------------------------------------------
# GET /welcome
# ---------------------------------------------------------------------------


async def test_welcome_no_intent_redirects_to_root(
    authenticated_client: AsyncClient,
):
    """User with no intent → dispatched to /."""
    response = await authenticated_client.get("/welcome", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/"


async def test_welcome_with_intent_no_clinician_redirects_to_verify(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """User with intent but no clinician → dispatched to /welcome/verify."""
    await _set_intent(db_test_session_manager, "testuser@example.com", "have_openings")
    response = await authenticated_client.get("/welcome", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/welcome/verify"


async def test_welcome_anon_redirects_to_login(test_client: AsyncClient):
    response = await test_client.get("/welcome", follow_redirects=False)
    assert response.status_code in {302, 401}


# ---------------------------------------------------------------------------
# GET /welcome/verify
# ---------------------------------------------------------------------------


async def test_get_verify_renders_200(authenticated_client: AsyncClient):
    response = await authenticated_client.get(
        "/welcome/verify",
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 200
    assert b"Verify your license" in response.content
    assert b'data-testid="verify-license-heading"' in response.content
    assert b'data-testid="welcome-step-header"' in response.content


async def test_get_verify_anon_redirected(test_client: AsyncClient):
    response = await test_client.get(
        "/welcome/verify",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 401}


# ---------------------------------------------------------------------------
# POST /welcome/verify
# ---------------------------------------------------------------------------


async def test_post_verify_happy_path_creates_provider_and_redirects(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Valid body → Provider + Licensure created, verification run, 302 to next step."""
    await _set_intent(db_test_session_manager, logged_in_user.email, "have_openings")

    response = await authenticated_client.post(
        "/welcome/verify",
        json=_VALID_BODY,
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    # Plain non-HTMX request → 302
    assert response.status_code == 302

    # Provider row created for this user
    async with db_test_session_manager() as session:
        result = await session.execute(
            select(Provider).filter(Provider.owner_id == logged_in_user.id)
        )
        providers = result.scalars().all()
    assert len(providers) == 1


async def test_post_verify_htmx_happy_path_returns_hx_redirect(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """HTMX request → 204 + HX-Redirect header instead of 302."""
    await _set_intent(db_test_session_manager, logged_in_user.email, "refer_now")

    response = await authenticated_client.post(
        "/welcome/verify",
        json=_VALID_BODY,
        headers={"Accept": "text/html", "HX-Request": "true"},
        follow_redirects=False,
    )
    assert response.status_code == 204
    assert "HX-Redirect" in response.headers


async def test_post_verify_invalid_body_returns_422_inline(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Bad body (missing required field) → form re-rendered with inline errors."""
    await _set_intent(db_test_session_manager, logged_in_user.email, "have_openings")

    bad_body = {**_VALID_BODY, "license_type": "not_a_valid_type"}
    response = await authenticated_client.post(
        "/welcome/verify",
        json=bad_body,
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 422
    # Form is re-rendered — heading still present
    assert b"Verify your license" in response.content


# ---------------------------------------------------------------------------
# GET /welcome/first-opening
# ---------------------------------------------------------------------------


async def test_get_first_opening_renders_when_clinician_verified(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """GET /welcome/first-opening renders the form when preconditions met."""
    await _setup_verified_clinician(
        authenticated_client,
        db_test_session_manager,
        logged_in_user.email,
        intent="have_openings",
    )
    response = await authenticated_client.get(
        "/welcome/first-opening",
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 200
    assert b"Describe one opening" in response.content
    assert b'data-testid="first-opening-type"' in response.content
    assert b'data-testid="welcome-step-header"' in response.content


async def test_get_first_opening_without_clinician_redirects_to_welcome(
    authenticated_client: AsyncClient,
):
    """GET /welcome/first-opening with no clinician → redirect to /welcome."""
    response = await authenticated_client.get(
        "/welcome/first-opening",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/welcome"


# ---------------------------------------------------------------------------
# POST /welcome/first-opening
# ---------------------------------------------------------------------------

_FIRST_OPENING_BODY = {
    "opening_type": "individual",
    "specialties": ["Trauma/PTSD", "Anxiety"],
    "availability_state": "taking_now",
}


async def test_post_first_opening_happy_path_creates_opening_and_redirects(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Valid body → Opening created, 302 to /welcome/done."""
    await _setup_verified_clinician(
        authenticated_client,
        db_test_session_manager,
        logged_in_user.email,
        intent="have_openings",
    )

    response = await authenticated_client.post(
        "/welcome/first-opening",
        json=_FIRST_OPENING_BODY,
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/welcome/done"

    # Verify a Post + OpeningDetail row was created
    async with db_test_session_manager() as session:
        result = await session.execute(
            select(Post).filter(
                Post.owner_id == logged_in_user.id,
                Post.kind == "clinician_opening",
            )
        )
        posts = result.scalars().all()
    assert len(posts) == 1


async def test_post_first_opening_sets_slot_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Slot fields written to OpeningDetail survive a read-back."""
    await _setup_verified_clinician(
        authenticated_client,
        db_test_session_manager,
        logged_in_user.email,
        intent="have_openings",
    )

    body = {
        **_FIRST_OPENING_BODY,
        "colleague_note": "Looking for adults with anxiety.",
    }
    response = await authenticated_client.post(
        "/welcome/first-opening",
        json=body,
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(OpeningDetail)
            .join(Post, Post.id == OpeningDetail.post_id)
            .filter(
                Post.owner_id == logged_in_user.id,
                Post.kind == "clinician_opening",
            )
        )
        detail = result.scalars().first()
    assert detail is not None
    assert detail.opening_type == "individual"
    assert detail.availability_state == "taking_now"
    assert detail.colleague_note == "Looking for adults with anxiety."


async def test_post_first_opening_skip_note_clears_colleague_note(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """skip_note=1 in body clears colleague_note before validation."""
    await _setup_verified_clinician(
        authenticated_client,
        db_test_session_manager,
        logged_in_user.email,
        intent="have_openings",
    )

    body = {
        **_FIRST_OPENING_BODY,
        "colleague_note": "This should be stripped",
        "skip_note": "1",
    }
    response = await authenticated_client.post(
        "/welcome/first-opening",
        json=body,
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(OpeningDetail)
            .join(Post, Post.id == OpeningDetail.post_id)
            .filter(
                Post.owner_id == logged_in_user.id,
            )
        )
        detail = result.scalars().first()
    assert detail is not None
    assert detail.colleague_note is None


async def test_post_first_opening_invalid_opening_type_returns_422(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Bad opening_type → form re-rendered with 422 inline errors."""
    await _setup_verified_clinician(
        authenticated_client,
        db_test_session_manager,
        logged_in_user.email,
        intent="have_openings",
    )

    bad_body = {**_FIRST_OPENING_BODY, "opening_type": "not_a_valid_type"}
    response = await authenticated_client.post(
        "/welcome/first-opening",
        json=bad_body,
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert b"Describe one opening" in response.content


# ---------------------------------------------------------------------------
# GET /welcome/done
# ---------------------------------------------------------------------------


async def test_get_done_renders_200(authenticated_client: AsyncClient):
    """GET /welcome/done always renders 200 with peer cards."""
    response = await authenticated_client.get(
        "/welcome/done",
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 200
    assert b"You're on the board" in response.content
    assert b'data-testid="likely-referral-sources"' in response.content


async def test_get_done_anon_redirected(test_client: AsyncClient):
    response = await test_client.get(
        "/welcome/done",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 401}


# ---------------------------------------------------------------------------
# GET /welcome/coming-soon
# ---------------------------------------------------------------------------


async def test_get_coming_soon_renders_200(authenticated_client: AsyncClient):
    response = await authenticated_client.get(
        "/welcome/coming-soon",
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 200
    assert b"coming soon" in response.content.lower()


# ---------------------------------------------------------------------------
# Helpers — setup a verified clinician (reused for be-findable tests)
# ---------------------------------------------------------------------------


async def _setup_verified_clinician(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    user_email: str,
    intent: str = "refer_now",
) -> None:
    await _set_intent(db_test_session_manager, user_email, intent)
    resp = await authenticated_client.post(
        "/welcome/verify",
        json=_VALID_BODY,
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert resp.status_code == 302


# ---------------------------------------------------------------------------
# GET /welcome/be-findable
# ---------------------------------------------------------------------------


async def test_get_be_findable_renders_when_clinician_exists(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await _setup_verified_clinician(
        authenticated_client, db_test_session_manager, logged_in_user.email
    )
    response = await authenticated_client.get(
        "/welcome/be-findable",
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 200
    assert b"Be findable" in response.content
    assert b'data-testid="be-findable-specialties"' in response.content
    assert b'data-testid="be-findable-modality"' in response.content


async def test_get_be_findable_without_clinician_redirects_to_welcome(
    authenticated_client: AsyncClient,
):
    response = await authenticated_client.get(
        "/welcome/be-findable",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/welcome"


async def test_get_be_findable_anon_redirected(test_client: AsyncClient):
    response = await test_client.get(
        "/welcome/be-findable",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 401}


# ---------------------------------------------------------------------------
# POST /welcome/be-findable
# ---------------------------------------------------------------------------


_BE_FINDABLE_BODY = {
    "specialties": ["Trauma/PTSD", "EMDR"],
    "in_person": True,
    "virtual": False,
}


async def test_post_be_findable_happy_path_updates_clinician_and_redirects(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Valid body → specialties + modality updated, 302 to /openings."""
    await _setup_verified_clinician(
        authenticated_client, db_test_session_manager, logged_in_user.email
    )

    response = await authenticated_client.post(
        "/welcome/be-findable",
        json=_BE_FINDABLE_BODY,
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    # has_reciprocity_profile → True → terminal /openings
    assert response.headers["location"] == "/openings"


async def test_post_be_findable_empty_submission_accepted(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Empty submission (skip) is accepted; state machine sends back to /welcome/be-findable."""
    await _setup_verified_clinician(
        authenticated_client, db_test_session_manager, logged_in_user.email
    )

    response = await authenticated_client.post(
        "/welcome/be-findable",
        json={"specialties": [], "in_person": False, "virtual": False},
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    # No profile → state machine routes back to be-findable
    assert response.headers["location"] == "/welcome/be-findable"
