"""Single source of truth for "can this user do X".

Routes (`write_authz`) and templates (Jinja global `capabilities`) call
into the same predicates so the visible UI affordance and the server-side
gate cannot disagree.

The two-claim model: a `User` may hold **Claim A** (verified clinician —
NPPES Type-1 + active license) and/or **Claim B** (verified org rep —
NPPES Type-2 + authority proven), per (user, org). Capabilities derive
from claim state; "solo / group / coordinator" labels are emergent, never
stored.

This module is a domain-logic predicate set: it reads `User`/`Clinician`/
`Organization`/`OrgRepresentation` structurally and returns booleans. It
lives in `domain/logic/` (not `framework/`) because framework code may
not import domain models — see `src/README.md` import discipline.

Phase status: placeholder bodies. The data columns the production
predicates will read (`Clinician.clinician_verified`, `Clinician.ever_verified_at`,
`Organization.org_verified`, `OrgRepresentation.authority_status`) do not
yet exist; this module returns conservative answers from the columns that
do exist (`User.is_verified`, `Clinician.npi`). Phase 2 of the rollout
tightens these reads once the schema lands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

# Reason codes used by `_locked.html` partials and `fix_url_for(...)`.
# Closed vocab: any new reason must be added here and mapped below.
REASON_EMAIL_UNVERIFIED = "email_unverified"
REASON_CLAIM_A_UNVERIFIED = "claim_a_unverified"
REASON_CLAIM_B_UNVERIFIED = "claim_b_unverified"
REASON_CLAIM_A_LAPSED = "claim_a_lapsed"
REASON_AFFILIATION_MISSING = "affiliation_missing"

_FIX_URLS = {
    REASON_EMAIL_UNVERIFIED: "/profile?focus=email",
    REASON_CLAIM_A_UNVERIFIED: "/profile?focus=claim_a",
    REASON_CLAIM_A_LAPSED: "/profile?focus=claim_a",
    REASON_CLAIM_B_UNVERIFIED: "/profile?focus=claim_b",
    REASON_AFFILIATION_MISSING: "/profile?focus=claim_b",
}


@dataclass(frozen=True)
class ClaimState:
    """Aggregate claim shape consumed by the profile-hub mode dispatcher
    and the claim-aware chrome banner.

    - `a`: True iff the user holds a verified Claim A (Verified Clinician).
    - `b`: set of org IDs the user is a verified rep for (Claim B per org).
    - `lapsed`: reason codes (see module-level REASON_* constants) for
      claims whose underlying requirements have regressed. A claim can be
      in both `a` (current cache true) and `lapsed` (a license just
      expired) simultaneously during the re-verify window.
    """

    a: bool = False
    b: frozenset[UUID] = field(default_factory=frozenset)
    lapsed: tuple[str, ...] = ()


def email_verified(user: Any) -> bool:
    """Email is the floor for every other claim. `User.is_verified` is
    fastapi-users' email-confirmation flag; do not overload it for
    clinician/org verification (per handoff §3)."""
    if user is None:
        return False
    return bool(getattr(user, "is_verified", False))


def clinician_verified(user: Any) -> bool:
    """Claim A: NPPES Type-1 name-matched + ≥1 active license.

    Placeholder: returns True when the user has emailed-verified AND owns
    at least one Clinician with a non-null `npi`. Phase 2 will read
    `Clinician.clinician_verified` (the denorm cache) once that column
    exists; until then, an NPI on file is the best signal available.
    """
    if not email_verified(user):
        return False
    clinicians = getattr(user, "clinicians", None) or ()
    return any(getattr(c, "npi", None) for c in clinicians)


def org_rep_verified(user: Any, org: Any) -> bool:
    """Claim B per (user, org). Placeholder: always False until the
    OrgRepresentation table lands in Phase 1 / Phase 4."""
    return False


def any_org_rep_verified(user: Any) -> bool:
    """True iff the user holds Claim B for at least one org. Placeholder:
    always False until OrgRepresentation lands."""
    return False


def can_read_full_feed(user: Any) -> bool:
    """Feed-teaser gate per handoff §7.1: full feed once any claim is
    verified; once-verified users retain read access after a lapse
    (`ever_verified_at`). Phase 0 placeholder: gate on current Claim A
    only — `ever_verified_at` doesn't exist yet."""
    if user is None:
        return False
    return clinician_verified(user) or any_org_rep_verified(user)


def can_post_referral(user: Any) -> bool:
    """Posting a referral as oneself requires Claim A (handoff §4.3)."""
    return clinician_verified(user)


def can_post_opening(user: Any) -> bool:
    """Posting a clinician opening requires Claim A (handoff §4.3)."""
    return clinician_verified(user)


def can_message(user: Any) -> bool:
    """Responding/messaging requires Claim A (handoff §4.3). The messages
    cluster does not yet exist; the predicate is shipped so it can be
    wired into route handlers the moment that cluster lands."""
    return clinician_verified(user)


def can_post_program_intake(user: Any, org: Any) -> bool:
    """Posting a program intake on behalf of an org requires Claim B for
    that org. Placeholder: always False until OrgRepresentation lands."""
    return org_rep_verified(user, org)


def can_post_org_referral(user: Any, org: Any, clinician: Any) -> bool:
    """Posting an org-attributed referral requires Claim B for the org
    AND the target clinician must have an active Affiliation to the org.
    Placeholder: always False until OrgRepresentation lands."""
    return False


def directory_listed(clinician: Any) -> bool:
    """A clinician is shown in the public directory iff their Claim A is
    verified (handoff §4.3: `directory.listed = clinician_verified`).
    Placeholder: presence of an NPI on the clinician row."""
    if clinician is None:
        return False
    return bool(getattr(clinician, "npi", None))


def can_save_favorite(user: Any) -> bool:
    """Saving a favorite requires email verification only (handoff §4.3)."""
    return email_verified(user)


def claim_state(user: Any) -> ClaimState:
    """Aggregate the per-claim flags into one object the profile-hub mode
    dispatcher consumes."""
    if user is None:
        return ClaimState()
    return ClaimState(
        a=clinician_verified(user),
        b=frozenset(),  # Phase 2 populates from OrgRepresentation rows.
        lapsed=(),  # Phase 2 populates from license-expiry + authority-revoked signals.
    )


def fix_url_for(reason: str) -> str:
    """Deep-link a "blocked action" partial into the relevant section of
    `/profile`. The closed reason vocab keeps the partial / route / banner
    from drifting. Unknown reasons fall back to the hub root."""
    return _FIX_URLS.get(reason, "/profile")
