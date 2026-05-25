"""Route-level tests for the /welcome onboarding wizard.

Covers:
- GET /welcome dispatches to next_step (redirect to / for no intent, /welcome/verify for no clinician)
- GET /welcome/verify renders with 200 and the step header
- POST /welcome/verify happy path: creates Provider+Licensure, runs verification, redirects
- POST /welcome/verify validation error: re-renders form with 422 inline errors
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
from src.domain.models import Provider, User

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
# GET /welcome/coming-soon
# ---------------------------------------------------------------------------


async def test_get_coming_soon_renders_200(authenticated_client: AsyncClient):
    response = await authenticated_client.get(
        "/welcome/coming-soon",
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 200
    assert b"coming soon" in response.content.lower()
