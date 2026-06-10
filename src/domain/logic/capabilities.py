"""Single source of truth for "can this user do X".

Routes (`write_authz`) and templates (Jinja global `capabilities`) call
into the same predicates so the visible UI affordance and the server-side
gate cannot disagree.

The two-claim model: a `User` may hold **Claim A** (verified clinician —
NPPES Type-1 name match) and/or **Claim B** (verified org rep —
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
feed read-access is gated on email + any current claim (the `ever_verified_at`
once-verified retention rule was removed — access reverts immediately when
the underlying claim lapses).

The predicates remain duck-typed via `getattr` so test stubs (and any
non-ORM Actor-like object) keep working without constructing real
SQLAlchemy rows. Templates and routes both call into the same surface,
so a visible affordance and its server-side gate can't disagree.

Capability trees compose from a small vocabulary of reusable leaves
(`_email_leaf`, `_clinician_verified_leaf`, `_org_rep_any_leaf`) — each
the single source of truth for that leaf's `(label_active, label_done,
fix_url)` triple. New `check_*` functions should build their tree from
existing leaf factories rather than re-declaring inline `Condition`
nodes, so the locked-affordance copy and deep-link for a given fact
stay identical across every capability that references it.

Fix URLs (`fix_url_for`, `reason_meta`) point at `/users/me` and its
subresource paths — the profile hub at `/profile` has been removed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

# Re-export the framework-layer tree primitives so existing callers
# (`check_can_read_feed`, tests, templates) keep working without changes.
# The types themselves are domain-agnostic and live in `src/framework/`.
from src.framework.access.capabilities.capabilities import (  # noqa: F401
    Bundle,
    CapabilityCheck,
    Condition,
    Gate,
)
from src.framework.dispatch.entity_spec import ReadPolicy

# Reason codes used by the `_shared/_locked.html` macros and
# `fix_url_for(...)`. Closed vocab: any new reason must be added here and
# given a `ReasonMeta` entry in `_REASON_META` below.
REASON_EMAIL_UNVERIFIED = "email_unverified"
# Network-access gate: the user hasn't cleared verification, so both
# read-side details (contact info, identity) and write-side affordances
# (create post CTA) are locked. Fixed by completing any verification
# path (Claim A or Claim B).
REASON_NETWORK_UNVERIFIED = "network_unverified"


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
    - `fix_url`: deep-link to where the reason gets fixed. The email
      reason points at `/users/me/email/form`; identity reasons point
      at `/users/me`, which hosts the Verification card and links to
      the relevant claim setup flows.

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
        fix_url="/users/me/email/form",
    ),
    REASON_NETWORK_UNVERIFIED: ReasonMeta(
        title="Provider network",
        unlock="Get provider network access to unlock this.",
        fix_label="Get access",
        fix_url="/users/me/access/capabilities/provider-network",
    ),
}

# Unknown reasons land here: a generic nudge into the hub root. Keeps a
# caller that passes an unmapped code from rendering an empty affordance.
_FALLBACK_META = ReasonMeta(
    title="Profile",
    unlock="Finish setting up your profile to unlock this.",
    fix_label="Open profile",
    fix_url="/users/me",
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
    """Claim A: NPPES Type-1 name-matched. Reads the
    `Clinician.clinician_verified` denorm cache so the predicate doesn't
    re-derive from `npi_match_status` per call. The cache is recomputed
    by `recompute_clinician_claim(...)` on every transition that touches
    its inputs."""
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


# ── Leaf factories ────────────────────────────────────────────────────────
#
# Each capability tree composes the same small vocabulary of boolean
# leaves: "email verified", "Claim A holder", "Claim B holder for some
# org". The factories below are the single source of truth for each
# leaf's `(label_active, label_done, fix_url)` triple — so when a
# second capability check reuses a leaf, the locked-affordance copy
# and the deep-link can't drift between them.
#
# Naming convention: `_<predicate>_leaf(user) -> Condition`. They are
# module-private; the public surface stays the top-level predicates
# (`email_verified` / `clinician_verified` / `any_org_rep_verified`)
# and the `check_*` functions that compose leaves into trees.


def _email_leaf(user: Any) -> Condition:
    return Condition(
        label_active="Verify your email",
        label_done="Email verified",
        met=email_verified(user),
        fix_url="/users/me/email/form",
    )


def _clinician_verified_leaf(user: Any) -> Condition:
    clinicians = getattr(user, "clinicians", None) or ()
    return Condition(
        label_active="Verify a clinician",
        label_done="Clinician verified",
        met=any(getattr(c, "clinician_verified", False) for c in clinicians),
        fix_url="/clinicians/form",
    )


def _org_rep_any_leaf(user: Any) -> Condition:
    return Condition(
        label_active="Verify your organization",
        label_done="Organization verified",
        met=bool(_verified_active_reps(user)),
        fix_url="/organizations/form",
    )


def check_network(user: Any) -> CapabilityCheck:
    """Structured capability check for full-feed read access.

    Tree: email_verified AND (clinician_verified OR org_rep_verified).
    `ever_verified_at` retention is intentionally excluded — access
    reverts immediately when the underlying claim lapses.
    """
    return CapabilityCheck(
        name="provider-network",
        description="See full provider details and reach out directly.",
        tree=Bundle(
            label_active="Provider network",
            label_done="Provider network",
            children=(
                _email_leaf(user),
                Gate(
                    label_active="Verify a clinician or organization",
                    label_done="Clinician or organization verified",
                    children=(
                        _clinician_verified_leaf(user),
                        _org_rep_any_leaf(user),
                    ),
                ),
            ),
        ),
    )


def can_access_network(user: Any) -> bool:
    """Feed-teaser gate: superuser bypass, otherwise delegates to
    `check_network`.

    Symmetric with `assert_can_access_network` — both forms grant
    superusers full read access regardless of claim state, so the
    route-level guard and the template-level affordance can't
    disagree about what a superuser sees. Without the bypass here,
    a superuser navigating around would clear the route's 403 check
    yet still see locked-popover affordances in templates that read
    `{% if can_access_network %}` or render `entity_link(...)` for
    a gated entity — a contradictory UX where the chrome treats the
    viewer as locked while the underlying page is open.
    """
    if getattr(user, "is_superuser", False):
        return True
    return check_network(user).granted


def assert_can_access_network(user: Any) -> None:
    """Raising form of `can_access_network`. Superuser bypass
    delegates to the predicate, which short-circuits first.

    Used as `ReadPolicy.assert_can_read` on entities whose data is
    restricted to verified network members (e.g. clinicians).
    """
    if not can_access_network(user):
        from src.framework.http.exceptions import ForbiddenError

        raise ForbiddenError(detail="Provider network access required.")


# Pre-built `ReadPolicy` for the network gate. Specs that want
# "verified-clinician-or-org-rep can read; everyone else 403s and sees a
# locked-link popover" set `read_policy=NETWORK_GATED_READ_POLICY` rather
# than re-declaring the same three-field `ReadPolicy(...)` block. No
# entity currently binds this — `USER_ENTITY`, `CLINICIAN_ENTITY`, and
# `ORGANIZATION_ENTITY` switched to per-row redaction (`_redacted=`
# template flag) so a viewer without network access can still browse
# the directories and see their own rows un-redacted. The constant is
# kept for any future entity whose entire surface should remain a
# binary gate (and so the predicates / reason code stay re-exportable
# under one name).
#
# Why a constant here and not a `network_gated()` factory or a flag on
# `EntitySpec`: ReadPolicy is structurally a tuple of (raiser, predicate,
# reason_code), and the three callables it bundles are themselves named
# domain facts (`assert_can_access_network`, `can_access_network`,
# `REASON_NETWORK_UNVERIFIED`). A frozen instance is the cheapest binding
# that points all three at the same gate; a factory would just be
# `lambda: ReadPolicy(...)` over the same args, and a flag would push
# this domain-specific tuple into the framework which doesn't otherwise
# know about Claim A/B.
NETWORK_GATED_READ_POLICY: ReadPolicy = ReadPolicy(
    assert_can_read=assert_can_access_network,
    can_read=can_access_network,
    lock_reason=REASON_NETWORK_UNVERIFIED,
)


def can_post_referral(user: Any) -> bool:
    """Self-path gate: posting a referral as the owning clinician requires
    Claim A (handoff §4.3). The org-rep authority path in
    `_assert_post_payload_authz` bypasses this check."""
    return clinician_verified(user)


def can_post_opening(user: Any) -> bool:
    """Self-path gate: posting a clinician opening as the owning clinician
    requires Claim A (handoff §4.3). The org-rep authority path in
    `_assert_post_payload_authz` bypasses this check."""
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
    """Deep-link a gated affordance to the relevant fix URL.
    Thin accessor over `reason_meta(reason).fix_url`, kept as a named
    function because routes/banners reference the URL without the rest of
    the metadata. Unknown reasons fall back to `/users/me`."""
    return reason_meta(reason).fix_url
