"""Parametrized truth-table tests for the onboarding state machine.

Each row covers one (intent, has_clinician, clinician_verified) combination
from the documented signal table in state_machine.py.
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
    "intent,has_clinician,clinician_verified,expected",
    [
        # No intent → landing
        (None, False, False, "/"),
        (None, True, True, "/"),
        # No clinician → verify
        ("refer_now", False, False, "/welcome/verify"),
        ("have_openings", False, False, "/welcome/verify"),
        ("building_network", False, False, "/welcome/verify"),
        ("invited", False, False, "/welcome/verify"),
        # Clinician exists but not verified → verify
        ("refer_now", True, False, "/welcome/verify"),
        ("have_openings", True, False, "/welcome/verify"),
        ("building_network", True, False, "/welcome/verify"),
        ("invited", True, False, "/welcome/verify"),
        # Clinician exists and verified → intent-specific stub (T4/T5/T7 replace)
        ("refer_now", True, True, _NOT_YET_BUILT),
        ("have_openings", True, True, _NOT_YET_BUILT),
        ("building_network", True, True, _NOT_YET_BUILT),
        ("invited", True, True, _NOT_YET_BUILT),
    ],
)
async def test_next_step_truth_table(
    intent, has_clinician, clinician_verified, expected
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

    # Mock db.execute so scalars().first() returns the fake verification.
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = fake_verification
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    result = await next_step(user, db=mock_db)
    assert result == expected
