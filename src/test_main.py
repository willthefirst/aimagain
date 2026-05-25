"""Pins the `lifespan` scheduler-gating contract, the onboarding-intent
pre-auth session flow, and the landing-page returner-skip rule.

Scheduler contract: DISABLE_SCHEDULER=1 skips the subsystem entirely
(no construction, no registration, no start), while the default path
constructs + registers + starts. The contract matters because APScheduler's
`add_job` logs "Adding job tentatively…" whenever a job is registered
against a not-yet-started scheduler — calling `register_jobs` on a disabled
scheduler is observable noise.

Onboarding intent: the landing page offers 4 intent cards. Anonymous visitors
POST to `/onboarding-intent-pending` which stores the value in the session and
redirects to `/auth/register`. `on_after_register` then transfers the session
value to the new user row. Tests here pin both legs of that flow.

Returner skip rule: `GET /` redirects authed users who already have an intent
AND own a verified clinician directly to `/openings`, bypassing the picker.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import User, Verification
from src.main import lifespan

pytestmark = pytest.mark.asyncio


# --- lifespan / scheduler -----------------------------------------------


async def test_lifespan_skips_scheduler_entirely_when_disabled(monkeypatch):
    monkeypatch.setenv("DISABLE_SCHEDULER", "1")

    with (
        patch("src.main.check_database_health", new=AsyncMock()),
        patch("src.main.make_scheduler") as mk,
        patch("src.main.register_jobs") as reg,
    ):
        async with lifespan(FastAPI()):
            pass

        mk.assert_not_called()
        reg.assert_not_called()


async def test_lifespan_starts_scheduler_when_enabled(monkeypatch):
    monkeypatch.delenv("DISABLE_SCHEDULER", raising=False)
    scheduler = MagicMock()

    with (
        patch("src.main.check_database_health", new=AsyncMock()),
        patch("src.main.make_scheduler", return_value=scheduler) as mk,
        patch("src.main.register_jobs") as reg,
    ):
        async with lifespan(FastAPI()):
            pass

        mk.assert_called_once()
        reg.assert_called_once_with(scheduler)
        scheduler.start.assert_called_once()
        scheduler.shutdown.assert_called_once_with(wait=False)


# --- Landing page template ----------------------------------------------


async def test_landing_page_renders_four_intent_cards(test_client: AsyncClient):
    """Anonymous GET / renders the 4-card intent picker with the correct
    `data-testid` attributes. The anonymous path uses plain form POSTs to
    `/onboarding-intent-pending`; these assertions catch copy edits that
    silently drop a card or mistype a testid."""
    response = await test_client.get("/", follow_redirects=False)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'data-testid="intent-refer-now"' in response.text
    assert 'data-testid="intent-have-openings"' in response.text
    assert 'data-testid="intent-invited"' in response.text
    assert 'data-testid="intent-building-network"' in response.text
    # Anonymous path submits plain forms to the pre-auth intent endpoint.
    assert "/onboarding-intent-pending" in response.text


# --- POST /onboarding-intent-pending ------------------------------------


async def test_pending_intent_valid_redirects_to_register(test_client: AsyncClient):
    """`POST /onboarding-intent-pending` with a valid intent redirects to
    `/auth/register`. The session cookie is set so the next request carries
    the intent."""
    response = await test_client.post(
        "/onboarding-intent-pending",
        data={"intent": "refer_now"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/register"


async def test_pending_intent_unknown_value_still_redirects(test_client: AsyncClient):
    """An unrecognised intent is silently ignored — the session key is not
    set, but the visitor still lands on `/auth/register` (no crash)."""
    response = await test_client.post(
        "/onboarding-intent-pending",
        data={"intent": "not_a_real_intent"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/register"


async def test_session_intent_persists_across_registration(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Full anonymous-to-registered flow:

    1. POST /onboarding-intent-pending  → stores `have_openings` in session
    2. POST /auth/register              → `on_after_register` reads session,
                                          writes `onboarding_intent` to user row,
                                          clears session key

    Tests run with `ENVIRONMENT=development`, so `on_after_register` also
    auto-verifies the user — but the important assertion is on the persisted
    `onboarding_intent` column.
    """
    # Step 1: store intent in session.
    intent_response = await test_client.post(
        "/onboarding-intent-pending",
        data={"intent": "have_openings"},
        follow_redirects=False,
    )
    assert intent_response.status_code == 302

    # Step 2: register a new user — same `test_client` carries the session cookie.
    email = "sessionflow@example.com"
    register_response = await test_client.post(
        "/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert register_response.status_code == 201

    # Step 3: verify the DB row has `onboarding_intent == "have_openings"`.
    async with db_test_session_manager() as session:
        from sqlalchemy import select

        result = await session.execute(select(User).where(User.email == email))
        user = result.scalars().first()
        assert user is not None
        assert (
            user.onboarding_intent == "have_openings"
        ), "on_after_register must transfer the session intent to the user row"


# --- GET / returner-skip rule -------------------------------------------


async def test_returner_skip_rule_redirects_when_intent_and_verified_clinician(
    authenticated_client: AsyncClient,
    logged_in_user: User,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    monkeypatch,
):
    """Authed user with `onboarding_intent` set AND a `verified` clinician
    is redirected from `/` to `/openings` (the returner-skip rule).

    `read_root` opens a session via `src.db.async_session_maker` (lazy
    import inside the function). Monkeypatching that module attribute
    redirects the handler to the test DB — the same pattern used by the
    job tests (`src/jobs/test_nightly_verification.py`)."""
    import src.db as _db_mod
    from tests.helpers import make_provider_with_org

    # Give the user an intent.
    async with db_test_session_manager() as session:
        from sqlalchemy import update

        await session.execute(
            update(User)
            .where(User.id == logged_in_user.id)
            .values(onboarding_intent="refer_now")
        )
        await session.commit()

    # Create a provider + verified Verification for that user.
    provider = make_provider_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)

    verif = Verification(provider_id=provider.id, status="verified")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(verif)

    # Redirect the lazy-imported session maker to the test DB.
    monkeypatch.setattr(_db_mod, "async_session_maker", db_test_session_manager)

    response = await authenticated_client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/openings"


async def test_returner_skip_rule_shows_picker_when_no_intent(
    authenticated_client: AsyncClient,
):
    """Authed user with NO `onboarding_intent` sees the intent picker, not
    a redirect — they haven't told us why they're here yet."""
    response = await authenticated_client.get("/", follow_redirects=False)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'data-testid="intent-refer-now"' in response.text


async def test_returner_skip_rule_shows_picker_when_intent_but_no_verified_clinician(
    authenticated_client: AsyncClient,
    logged_in_user: User,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    monkeypatch,
):
    """Authed user with an intent but no verified clinician still sees the
    picker — the skip rule requires BOTH conditions."""
    import src.db as _db_mod
    from tests.helpers import make_provider_with_org

    # Give the user an intent.
    async with db_test_session_manager() as session:
        from sqlalchemy import update

        await session.execute(
            update(User)
            .where(User.id == logged_in_user.id)
            .values(onboarding_intent="have_openings")
        )
        await session.commit()

    # Create a provider with a `needs_review` Verification (not verified).
    provider = make_provider_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)

    verif = Verification(provider_id=provider.id, status="needs_review")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(verif)

    # Redirect the lazy-imported session maker to the test DB.
    monkeypatch.setattr(_db_mod, "async_session_maker", db_test_session_manager)

    response = await authenticated_client.get("/", follow_redirects=False)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'data-testid="intent-refer-now"' in response.text
