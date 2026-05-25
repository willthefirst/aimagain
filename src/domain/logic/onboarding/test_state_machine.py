"""Parametrized truth-table tests for the onboarding state machine.

Each row covers one (intent, has_clinician, clinician_verified, has_opening,
has_profile) combination from the documented signal table in state_machine.py.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.logic.onboarding.state_machine import (
    has_reciprocity_profile,
    next_step,
    onboarding_clinician,
)

pytestmark = pytest.mark.asyncio

_NOT_YET_BUILT = "/welcome/coming-soon"


# ---------------------------------------------------------------------------
# onboarding_clinician helper
# ---------------------------------------------------------------------------


def _make_provider(
    created_at_offset: int = 0,
    specialties=None,
    in_person_sessions="please_contact",
    virtual_sessions="please_contact",
):
    """Create a minimal fake Provider with a predictable created_at."""
    from datetime import datetime, timedelta

    aff = MagicMock()
    aff.specialties = specialties if specialties is not None else []
    aff.in_person_sessions = in_person_sessions
    aff.virtual_sessions = virtual_sessions

    p = MagicMock()
    p.id = uuid.uuid4()
    p.created_at = datetime(2024, 1, 1) + timedelta(days=created_at_offset)
    p.primary_affiliation = aff
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
# has_reciprocity_profile predicate
# ---------------------------------------------------------------------------


def test_has_reciprocity_profile_false_when_no_affiliation():
    p = MagicMock()
    p.primary_affiliation = None
    assert has_reciprocity_profile(p) is False


def test_has_reciprocity_profile_false_when_no_specialties():
    p = _make_provider(specialties=[], in_person_sessions="yes")
    assert has_reciprocity_profile(p) is False


def test_has_reciprocity_profile_false_when_no_modality():
    p = _make_provider(
        specialties=["Trauma/PTSD"], in_person_sessions="no", virtual_sessions="no"
    )
    assert has_reciprocity_profile(p) is False


def test_has_reciprocity_profile_false_when_only_specialties():
    p = _make_provider(
        specialties=["Anxiety"],
        in_person_sessions="please_contact",
        virtual_sessions="please_contact",
    )
    assert has_reciprocity_profile(p) is False


def test_has_reciprocity_profile_true_with_in_person():
    p = _make_provider(specialties=["Trauma/PTSD"], in_person_sessions="yes")
    assert has_reciprocity_profile(p) is True


def test_has_reciprocity_profile_true_with_virtual():
    p = _make_provider(specialties=["EMDR"], virtual_sessions="yes")
    assert has_reciprocity_profile(p) is True


def test_has_reciprocity_profile_true_with_both_modalities():
    p = _make_provider(
        specialties=["Anxiety", "Depression"],
        in_person_sessions="yes",
        virtual_sessions="yes",
    )
    assert has_reciprocity_profile(p) is True


# ---------------------------------------------------------------------------
# next_step truth table
# ---------------------------------------------------------------------------


def _make_verified_result():
    v = MagicMock()
    v.status = "verified"
    return v


def _make_unverified_result():
    v = MagicMock()
    v.status = "needs_review"
    return v


@pytest.mark.parametrize(
    "intent,has_clinician,clinician_verified,has_opening,has_profile,expected",
    [
        # No intent → landing
        (None, False, False, False, False, "/"),
        (None, True, True, False, False, "/"),
        # No clinician → verify
        ("refer_now", False, False, False, False, "/welcome/verify"),
        ("have_openings", False, False, False, False, "/welcome/verify"),
        ("building_network", False, False, False, False, "/welcome/verify"),
        ("invited", False, False, False, False, "/welcome/verify"),
        # Clinician exists but not verified → verify
        ("refer_now", True, False, False, False, "/welcome/verify"),
        ("have_openings", True, False, False, False, "/welcome/verify"),
        ("building_network", True, False, False, False, "/welcome/verify"),
        ("invited", True, False, False, False, "/welcome/verify"),
        # refer_now: verified + no reciprocity profile → be-findable
        ("refer_now", True, True, False, False, "/welcome/be-findable"),
        # refer_now: verified + has profile → openings (terminal)
        ("refer_now", True, True, False, True, "/openings"),
        # have_openings, verified, no opening yet → first-opening step
        ("have_openings", True, True, False, False, "/welcome/first-opening"),
        # have_openings, verified, has opening → done
        ("have_openings", True, True, True, False, "/welcome/done"),
        # building_network / invited: stub (T7 replaces)
        ("building_network", True, True, False, False, _NOT_YET_BUILT),
        ("invited", True, True, False, False, _NOT_YET_BUILT),
    ],
)
async def test_next_step_truth_table(
    intent, has_clinician, clinician_verified, has_opening, has_profile, expected
):
    in_person = "yes" if has_profile else "no"
    specialties = ["Trauma/PTSD"] if has_profile else []
    provider = _make_provider(
        specialties=specialties,
        in_person_sessions=in_person,
    )
    user = MagicMock()
    user.onboarding_intent = intent
    user.providers = [provider] if has_clinician else []

    fake_verification = (
        _make_verified_result()
        if (has_clinician and clinician_verified)
        else (_make_unverified_result() if has_clinician else None)
    )

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
