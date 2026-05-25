"""Parametrized truth-table tests for the onboarding state machine.

Each row covers one (intent, has_clinician, clinician_verified, has_opening)
combination from the documented signal table in state_machine.py.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.logic.onboarding.state_machine import next_step, onboarding_clinician

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# onboarding_clinician helper
# ---------------------------------------------------------------------------


def _make_provider(created_at_offset: int = 0):
    """Create a minimal fake Provider with a predictable created_at."""
    from datetime import datetime, timedelta

    p = MagicMock()
    p.id = uuid.uuid4()
    p.created_at = datetime(2024, 1, 1) + timedelta(days=created_at_offset)
    return p


def test_onboarding_clinician_returns_none_for_no_providers():
    user = MagicMock()
    user.providers = []
    assert onboarding_clinician(user) is None


def test_onboarding_clinician_returns_most_recent():
    p1 = _make_provider(0)
    p2 = _make_provider(5)
    p3 = _make_provider(3)
    user = MagicMock()
    user.providers = [p1, p2, p3]
    assert onboarding_clinician(user) is p2  # latest by created_at


def test_onboarding_clinician_single_provider():
    p = _make_provider(0)
    user = MagicMock()
    user.providers = [p]
    assert onboarding_clinician(user) is p


# ---------------------------------------------------------------------------
# next_step truth table
# ---------------------------------------------------------------------------

_NOT_YET_BUILT = "/welcome/coming-soon"


@pytest.mark.parametrize(
    "intent,has_clinician,clinician_verified,has_opening,expected",
    [
        # No intent → landing
        (None, False, False, False, "/"),
        (None, True, True, False, "/"),
        # No clinician → verify
        ("refer_now", False, False, False, "/welcome/verify"),
        ("have_openings", False, False, False, "/welcome/verify"),
        ("building_network", False, False, False, "/welcome/verify"),
        ("invited", False, False, False, "/welcome/verify"),
        # Clinician exists but not verified → verify
        ("refer_now", True, False, False, "/welcome/verify"),
        ("have_openings", True, False, False, "/welcome/verify"),
        ("building_network", True, False, False, "/welcome/verify"),
        ("invited", True, False, False, "/welcome/verify"),
        # Clinician verified, other intents → stub (T5/T7 will replace)
        ("refer_now", True, True, False, _NOT_YET_BUILT),
        ("building_network", True, True, False, _NOT_YET_BUILT),
        ("invited", True, True, False, _NOT_YET_BUILT),
        # have_openings, verified, no opening yet → first-opening step
        ("have_openings", True, True, False, "/welcome/first-opening"),
        # have_openings, verified, has opening → done
        ("have_openings", True, True, True, "/welcome/done"),
    ],
)
async def test_next_step_truth_table(
    intent, has_clinician, clinician_verified, has_opening, expected
):
    provider = _make_provider()
    user = MagicMock()
    user.onboarding_intent = intent
    user.providers = [provider] if has_clinician else []

    # Build a fake Verification with the requested status, or None.
    if has_clinician and clinician_verified:
        fake_verification = MagicMock()
        fake_verification.status = "verified"
    elif has_clinician and not clinician_verified:
        fake_verification = MagicMock()
        fake_verification.status = "needs_review"
    else:
        fake_verification = None

    # Mock db.execute to return the fake verification first, then simulate
    # the has_opening query. The state machine calls execute once for
    # verification, and (for have_openings+verified) once for openings.
    fake_post = MagicMock() if has_opening else None

    call_count = 0

    def _side_effect(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalars.return_value.first.return_value = fake_verification
        else:
            result.scalars.return_value.first.return_value = fake_post
        return result

    mock_db = AsyncMock()
    mock_db.execute.side_effect = _side_effect

    result = await next_step(user, db=mock_db)
    assert result == expected
