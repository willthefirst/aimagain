"""Score a verification attempt from the NPPES + OIG primitives.

Table-driven, deterministic; no I/O. The orchestrator (#528 / A4) feeds
:func:`score_verification` the outputs of :func:`nppes_lookup` and
:func:`oig_check`, plus the clinician's first/last name as currently
recorded, and gets back a :class:`Score` ready to persist on the
`Verification` row.

Rules (in order):

* `oig.match` → ``failed``, flag ``oig_excluded:{reason}``.
* `not nppes.found` → ``failed``, flag ``nppes_npi_not_found``.
* NPPES-vs-clinician name similarity < ``_NAME_MATCH_THRESHOLD`` →
  ``needs_review``, flag ``nppes_name_mismatch``.
* Otherwise → ``verified``.

The similarity threshold is conservative on purpose — the cost of a
false-negative "needs_review" (a human looks at a row that was
actually fine) is low; the cost of a false-positive "verified"
(a name that shouldn't have matched slipped through silently) is
higher.
"""

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from .nppes import NppesResult
from .oig import OigResult

_NAME_MATCH_THRESHOLD: float = 0.80


VerificationStatus = Literal["verified", "needs_review", "failed"]


@dataclass(frozen=True, slots=True)
class Score:
    """Output of the scoring layer; consumed directly by
    `VerificationRepository.record(...)`."""

    status: VerificationStatus
    flags: list[str]
    name_match_score: float | None


def _name_similarity(a: str, b: str) -> float:
    """Case-insensitive similarity in `[0.0, 1.0]` between two full
    names, comparing the lower-cased `"first last"` form. Whitespace is
    not normalized beyond `.lower()` — both inputs are caller-controlled
    strings already trimmed by the schema layer (`StrippedText`)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def score_verification(
    *,
    nppes: NppesResult,
    oig: OigResult,
    provider_first_name: str,
    provider_last_name: str,
) -> Score:
    """Score a verification attempt from the primitives.

    Returns ``Score(status, flags, name_match_score)``. `flags` carries
    the closed-vocabulary tokens documented in the module docstring;
    `name_match_score` is ``None`` whenever NPPES wasn't queried (no
    NPI on file) or NPPES returned no results.
    """
    # Hard disqualifier first — an OIG hit overrides everything else.
    # `reason` is part of the flag token so the reviewer sees whether it
    # was a high-confidence NPI hit or a softer name hit.
    if oig.match:
        flag = f"oig_excluded:{oig.reason or 'unknown'}"
        return Score(status="failed", flags=[flag], name_match_score=None)

    if not nppes.found:
        return Score(
            status="failed",
            flags=["nppes_npi_not_found"],
            name_match_score=None,
        )

    # NPPES returned a record; compare names. Missing first/last name on
    # the NPPES side counts as a mismatch — a record without a name we
    # can compare isn't a "verified" identity match.
    nppes_full = f"{nppes.first_name or ''} {nppes.last_name or ''}".strip()
    provider_full = f"{provider_first_name} {provider_last_name}".strip()
    similarity = _name_similarity(nppes_full, provider_full)

    if similarity < _NAME_MATCH_THRESHOLD:
        return Score(
            status="needs_review",
            flags=["nppes_name_mismatch"],
            name_match_score=similarity,
        )

    return Score(status="verified", flags=[], name_match_score=similarity)
