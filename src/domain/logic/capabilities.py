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

Phase status: production reads. `clinician_verified` consults the
`Clinician.clinician_verified` denorm cache; `org_rep_verified(user, org)`
walks `User.org_representations` against `Organization.org_verified`;
feed read-access honors `Clinician.ever_verified_at` (the once-verified
retention rule per handoff §7.1).

The predicates remain duck-typed via `getattr` so test stubs (and any
non-ORM Actor-like object) keep working without constructing real
SQLAlchemy rows. Templates and routes both call into the same surface,
so a visible affordance and its server-side gate can't disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

# Reason codes used by the `_shared/_locked.html` macros and
# `fix_url_for(...)`. Closed vocab: any new reason must be added here and
# given a `ReasonMeta` entry in `_REASON_META` below.
REASON_EMAIL_UNVERIFIED = "email_unverified"
REASON_CLAIM_A_UNVERIFIED = "claim_a_unverified"
REASON_CLAIM_B_UNVERIFIED = "claim_b_unverified"
REASON_CLAIM_A_LAPSED = "claim_a_lapsed"
REASON_CLAIM_B_LAPSED = "claim_b_lapsed"
REASON_AFFILIATION_MISSING = "affiliation_missing"
# Read-side gate (not a write affordance): the viewer hasn't cleared
# verification, so contact/identity details on a post detail are withheld
# (`can_read_full_feed` is False). Distinct from the claim-to-*post*
# reasons above — this one fixes by completing any verification path.
REASON_VIEW_UNVERIFIED = "view_unverified"


@dataclass(frozen=True)
class ReasonMeta:
    """The human-facing half of a gating reason: everything a locked
    affordance needs to render, in one place.

    - `title`: short claim/section name ("Clinician identity"). Used where
      the affordance carries its own heading — e.g. the re-verify card's
      `<strong>` — so the template doesn't re-derive a per-reason title.
    - `unlock`: imperative sentence shown under a disabled action, in place
      of a withheld field, or as the re-verify card's body ("Add a verified
      clinician profile to unlock this.").
    - `fix_label`: CTA link text ("Complete clinician setup").
    - `fix_url`: deep-link to where the reason gets fixed. The two
      onboarding-floor reasons (email, claim A) point at their dedicated
      step subroute (`/profile/email`, `/profile/identity`); the additive
      and lapsed reasons point at the hub root (`/profile`), which
      mode-dispatches them (add-a-claim / re-verify / manage).

    Templates read this via the `capabilities.reason_meta(reason)` Jinja
    global so a given reason reads identically on every surface — the
    copy lives here, never inline in a template. Adding a reason without
    a `ReasonMeta` entry falls back to the generic hub pointer.
    """

    title: str
    unlock: str
    fix_label: str
    fix_url: str


_REASON_META = {
    REASON_EMAIL_UNVERIFIED: ReasonMeta(
        title="Email verification",
        unlock="Verify your email to unlock this.",
        fix_label="Verify email",
        fix_url="/profile/email",
    ),
    REASON_CLAIM_A_UNVERIFIED: ReasonMeta(
        title="Clinician identity",
        unlock="Add a verified clinician profile to unlock this.",
        fix_label="Complete clinician setup",
        fix_url="/profile/identity",
    ),
    REASON_CLAIM_A_LAPSED: ReasonMeta(
        title="Clinician identity",
        unlock="Re-attest your license to resume this.",
        fix_label="Re-verify license",
        fix_url="/profile",
    ),
    REASON_CLAIM_B_UNVERIFIED: ReasonMeta(
        title="Organization representation",
        unlock="Become a verified organization representative to unlock this.",
        fix_label="Complete organization setup",
        fix_url="/profile",
    ),
    REASON_CLAIM_B_LAPSED: ReasonMeta(
        title="Organization representation",
        unlock="Re-verify your authority to resume this.",
        fix_label="Re-verify authority",
        fix_url="/profile",
    ),
    REASON_AFFILIATION_MISSING: ReasonMeta(
        title="Clinician affiliation",
        unlock="Add a clinician affiliation to unlock this.",
        fix_label="Manage affiliations",
        fix_url="/profile",
    ),
    REASON_VIEW_UNVERIFIED: ReasonMeta(
        title="Contact details",
        unlock="Verify your account to see contact details.",
        fix_label="Complete verification",
        fix_url="/profile",
    ),
}

# Unknown reasons land here: a generic nudge into the hub root. Keeps a
# caller that passes an unmapped code from rendering an empty affordance.
_FALLBACK_META = ReasonMeta(
    title="Profile",
    unlock="Finish setting up your profile to unlock this.",
    fix_label="Open profile",
    fix_url="/profile",
)


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
    """Claim A: NPPES Type-1 name-matched + ≥1 active license. Reads the
    `Clinician.clinician_verified` denorm cache so the predicate doesn't
    re-derive from `npi_match_status` + licensure status per call. The
    cache is recomputed by `recompute_clinician_claim(...)` on every
    transition that touches its inputs."""
    if not email_verified(user):
        return False
    clinicians = getattr(user, "clinicians", None) or ()
    return any(getattr(c, "clinician_verified", False) for c in clinicians)


def _verified_active_reps(user: Any) -> tuple[Any, ...]:
    """Filter `user.org_representations` to currently-verified, non-
    archived rows. Used by `any_org_rep_verified` / `org_rep_verified` /
    `claim_state` so the predicate set has a single way to read this."""
    reps = getattr(user, "org_representations", None) or ()
    return tuple(
        r
        for r in reps
        if getattr(r, "authority_status", None) == "verified"
        and getattr(r, "archived_at", None) is None
    )


def org_rep_verified(user: Any, org: Any) -> bool:
    """Claim B for `(user, org)`. Requires:

    1. The user's email is verified (floor for every claim).
    2. The org's Type-2 NPI is `Organization.org_verified` (cached when
       NPPES confirms — verified once per org).
    3. The user holds a `verified` + non-archived `OrgRepresentation`
       for this org.
    """
    if not email_verified(user):
        return False
    if not getattr(org, "org_verified", False):
        return False
    org_id = getattr(org, "id", None)
    if org_id is None:
        return False
    return any(
        getattr(r, "org_id", None) == org_id for r in _verified_active_reps(user)
    )


def any_org_rep_verified(user: Any) -> bool:
    """True iff the user holds at least one verified, non-archived
    OrgRepresentation. Skips the per-org `org_verified` gate — Claim B
    by-any-org is a coarser check that the feed and chrome use to know
    whether the user has *some* org-rep status, regardless of which
    specific org is in scope."""
    if not email_verified(user):
        return False
    return bool(_verified_active_reps(user))


def can_read_full_feed(user: Any) -> bool:
    """Feed-teaser gate per handoff §7.1: full feed once any claim is
    verified; once-verified users retain read access after a lapse
    (`ever_verified_at`). New users see the blurred teaser until they
    clear the first verification."""
    if user is None:
        return False
    if clinician_verified(user) or any_org_rep_verified(user):
        return True
    clinicians = getattr(user, "clinicians", None) or ()
    return any(getattr(c, "ever_verified_at", None) for c in clinicians)


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
    AND the target clinician must have an active ClinicianAffiliation to the org
    (handoff §4.3 / §10.5)."""
    if not org_rep_verified(user, org):
        return False
    org_id = getattr(org, "id", None)
    affiliations = getattr(clinician, "clinician_affiliations", None) or ()
    return any(getattr(a, "org_id", None) == org_id for a in affiliations)


def directory_listed(clinician: Any) -> bool:
    """A clinician is shown in the public directory iff their Claim A is
    verified (handoff §4.3: `directory.listed = clinician_verified`).
    Reads the `Clinician.clinician_verified` denorm cache."""
    if clinician is None:
        return False
    return bool(getattr(clinician, "clinician_verified", False))


def can_save_favorite(user: Any) -> bool:
    """Saving a favorite requires email verification only (handoff §4.3)."""
    return email_verified(user)


def claim_state(user: Any) -> ClaimState:
    """Aggregate the per-claim flags into one object the profile-hub mode
    dispatcher consumes.

    `b` is the set of org IDs the user is a verified rep for; the
    profile hub's mode dispatcher reads `not state.a and not state.b`
    to land on `setup` mode. `lapsed` tracking (license expiry,
    authority revocation) lands when Phase 3 introduces the per-
    transition recompute helpers; until then it stays empty so the
    hub never spuriously surfaces a `re-verify` mode.
    """
    if user is None:
        return ClaimState()
    rep_org_ids = frozenset(
        getattr(r, "org_id", None) for r in _verified_active_reps(user)
    ) - {None}
    return ClaimState(
        a=clinician_verified(user),
        b=rep_org_ids,
        lapsed=(),
    )


def reason_meta(reason: str) -> ReasonMeta:
    """Resolve a `REASON_*` code to its human-facing copy + fix link.

    Single source for the text a locked affordance shows. Templates call
    this as a Jinja global (`capabilities.reason_meta(reason)`); routes /
    banners that only need the URL call `fix_url_for` (a thin accessor over
    this). Unknown reasons return `_FALLBACK_META` so a stray code renders
    a sane nudge rather than blank chrome."""
    return _REASON_META.get(reason, _FALLBACK_META)


def fix_url_for(reason: str) -> str:
    """Deep-link a gated affordance into the relevant section of `/profile`.
    Thin accessor over `reason_meta(reason).fix_url`, kept as a named
    function because routes/banners reference the URL without the rest of
    the metadata. Unknown reasons fall back to the hub root."""
    return reason_meta(reason).fix_url
