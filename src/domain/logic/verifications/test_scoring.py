"""Tests for `score_verification`.

Table-driven across the four rule branches in the scoring docstring
plus a few boundary cases (name match exactly at the threshold, no
NPPES names present).
"""

import pytest

from src.domain.logic.verifications.nppes import NppesResult
from src.domain.logic.verifications.oig import OigResult
from src.domain.logic.verifications.scoring import score_verification


def _nppes(found: bool, first: str = "", last: str = "") -> NppesResult:
    return NppesResult(
        found=found,
        first_name=first or None,
        last_name=last or None,
        raw=None,
    )


def _oig(match: bool, reason=None) -> OigResult:
    return OigResult(match=match, reason=reason)


# --- Rule 1: OIG match → failed -----------------------------------------


def test_score_oig_npi_match_returns_failed():
    score = score_verification(
        nppes=_nppes(True, "Alice", "Doe"),
        oig=_oig(True, "npi_match"),
        provider_first_name="Alice",
        provider_last_name="Doe",
    )
    assert score.status == "failed"
    assert score.flags == ["oig_excluded:npi_match"]
    assert score.name_match_score is None


def test_score_oig_name_match_returns_failed():
    score = score_verification(
        nppes=_nppes(True, "Alice", "Doe"),
        oig=_oig(True, "name_match"),
        provider_first_name="Alice",
        provider_last_name="Doe",
    )
    assert score.status == "failed"
    assert score.flags == ["oig_excluded:name_match"]


def test_score_oig_match_with_unknown_reason_still_flags():
    """Defensive: an OIG result with `match=True, reason=None` (shouldn't
    happen in practice but the type allows it) still produces a flag —
    `oig_excluded:unknown`."""
    score = score_verification(
        nppes=_nppes(True, "X", "Y"),
        oig=OigResult(match=True, reason=None),  # type: ignore[arg-type]
        provider_first_name="X",
        provider_last_name="Y",
    )
    assert score.status == "failed"
    assert score.flags == ["oig_excluded:unknown"]


def test_score_oig_match_overrides_nppes_not_found():
    """OIG is a hard disqualifier — it wins even if NPPES would also
    have failed. The flag is the OIG one (the bigger signal)."""
    score = score_verification(
        nppes=_nppes(False),
        oig=_oig(True, "npi_match"),
        provider_first_name="Alice",
        provider_last_name="Doe",
    )
    assert score.status == "failed"
    assert score.flags == ["oig_excluded:npi_match"]


# --- Rule 2: NPPES not found → failed -----------------------------------


def test_score_nppes_not_found_returns_failed():
    score = score_verification(
        nppes=_nppes(False),
        oig=_oig(False),
        provider_first_name="Alice",
        provider_last_name="Doe",
    )
    assert score.status == "failed"
    assert score.flags == ["nppes_npi_not_found"]
    assert score.name_match_score is None


# --- Rule 3: Name similarity below threshold → needs_review -------------


def test_score_name_mismatch_returns_needs_review():
    score = score_verification(
        nppes=_nppes(True, "Alice", "Smith"),
        oig=_oig(False),
        provider_first_name="Bartholomew",
        provider_last_name="Jenkins",
    )
    assert score.status == "needs_review"
    assert score.flags == ["nppes_name_mismatch"]
    # Score is reported for the reviewer even when it's below threshold.
    assert 0.0 <= score.name_match_score < 0.80


def test_score_empty_nppes_names_count_as_mismatch():
    """A NPPES record without names can't be compared — the empty-vs-
    populated similarity is 0, so we land in `needs_review`."""
    score = score_verification(
        nppes=_nppes(True),  # no names
        oig=_oig(False),
        provider_first_name="Alice",
        provider_last_name="Doe",
    )
    assert score.status == "needs_review"
    assert score.flags == ["nppes_name_mismatch"]
    assert score.name_match_score == pytest.approx(0.0)


# --- Rule 4: Otherwise → verified ---------------------------------------


def test_score_exact_name_match_returns_verified():
    score = score_verification(
        nppes=_nppes(True, "Alice", "Doe"),
        oig=_oig(False),
        provider_first_name="Alice",
        provider_last_name="Doe",
    )
    assert score.status == "verified"
    assert score.flags == []
    assert score.name_match_score == pytest.approx(1.0)


def test_score_name_match_is_case_insensitive():
    """`Alice Doe` and `alice doe` are the same person — the scoring
    layer lower-cases before comparing."""
    score = score_verification(
        nppes=_nppes(True, "ALICE", "DOE"),
        oig=_oig(False),
        provider_first_name="alice",
        provider_last_name="doe",
    )
    assert score.status == "verified"
    assert score.name_match_score == pytest.approx(1.0)


def test_score_close_but_above_threshold_returns_verified():
    """A close-but-not-exact name (typo or middle name) above the 0.80
    threshold should still verify."""
    score = score_verification(
        nppes=_nppes(True, "Alice", "Doe"),
        oig=_oig(False),
        provider_first_name="Allice",  # extra 'l' typo
        provider_last_name="Doe",
    )
    assert score.status == "verified"
    assert score.name_match_score is not None
    assert score.name_match_score >= 0.80
