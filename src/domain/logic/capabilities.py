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
held in the `LEAVES` registry (`EMAIL_LEAF`, `CLINICIAN_VERIFIED_LEAF`,
`ORG_REP_ANY_LEAF`, `OWNS_PROGRAM_LEAF`, `SUPERUSER_LEAF`). Each `Leaf`
is the single source of truth for its `(label_active, label_done,
fix_url)` triple and predicate; capability `check_*` functions compose
trees by calling `leaf.evaluate(actor)` rather than re-declaring
`Condition` nodes inline. The framework's `LeafRegistry` (see
`src/framework/access/capabilities/capabilities.py`) is the DAG node
table — `LEAVES.all()` is the introspection surface for "every fact
this app gates on".

**Superuser policy — superusers hold every capability.** The policy has
one home, the `superuser(user)` predicate. Every boolean `can_*` gate
consults it first; every tree-based `check_*` composes it via
`_superuser_gate`, which OR-wraps the real requirement tree with a
`Superuser` condition *only when the viewer holds it* — normal users
never see the override branch, superusers see exactly why they're
granted. `check_superuser` exposes the override as its own capability
on `/users/me/access/capabilities`, again only for holders (it returns
``None`` otherwise, which the framework treats as 404/omitted).
Row-level admin rights (edit/delete another user's rows) are a separate
authz axis (`src/framework/access/authz`) and are not modeled here.

To add a new entity-dependency leaf:

1. Write the boolean predicate (`def has_X(actor) -> bool`).
2. Construct a `Leaf` with its labels, fix URL, and the predicate.
3. Register it: `X_LEAF = LEAVES.register(Leaf(...))`.
4. Reference `X_LEAF.evaluate(user)` from the relevant capability tree.

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
    Leaf,
    LeafRegistry,
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
REASON_NOT_A_VERIFIED_PROVIDER = "network_unverified"
# Program-intake gate: the user can't currently publish a program-intake
# post on /posts/form. Three sub-conditions feed it (email + verified
# org rep + an owned program); the capability detail page renders the
# tree so the user can see exactly which step is open.
REASON_PROGRAM_INTAKE_LOCKED = "program_intake_locked"


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
    REASON_NOT_A_VERIFIED_PROVIDER: ReasonMeta(
        title="Provider network",
        unlock="Get provider network access to unlock this.",
        fix_label="Get access",
        fix_url="/users/me/access/capabilities/provider-network",
    ),
    REASON_PROGRAM_INTAKE_LOCKED: ReasonMeta(
        title="Program intake",
        unlock="Verify your organization and add a program to unlock this.",
        fix_label="Get access",
        fix_url="/users/me/access/capabilities/program-intake",
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


def superuser(user: Any) -> bool:
    """Operational override: superusers hold every capability. This is
    the single home for that policy — every `can_*` predicate consults
    it first, and the tree-based `check_*` functions compose it via
    `_superuser_gate` so the capability UI shows the override as an
    explicit OR branch instead of silently flipping `granted`.

    Deliberately NOT a claim and NOT consulted by the leaf *facts*
    (`email_verified`, `clinician_verified`, …): being a superuser
    doesn't make your email verified — it makes the verification
    unnecessary. Facts stay factual; only capability grants override.
    """
    if user is None:
        return False
    return bool(getattr(user, "is_superuser", False))


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


def owns_program(user: Any) -> bool:
    """True iff the user owns at least one `Program`. Reads the
    `User.programs` selectin relationship; the create flow at
    `/programs/form` is what flips this bit. Note: this doesn't filter
    by the program's org being verified — the per-row write gate in
    `_assert_post_payload_capability` re-checks `org_rep_verified` for
    the specific program's org at create time, so the picker only needs
    the "has any program" shape here."""
    if user is None:
        return False
    return bool(getattr(user, "programs", None) or ())


# ── Leaf registry ─────────────────────────────────────────────────────────
#
# `LEAVES` is the DAG's node table. Each registered `Leaf` is the single
# source of truth for one fact's `(label_active, label_done, fix_url)`
# and predicate; capability `check_*` functions compose trees by
# calling `LEAF.evaluate(user)` rather than re-declaring inline
# `Condition` blocks. Re-registering a name raises (the framework
# enforces insert-once), so a typo or accidental re-import can't
# shadow an existing fact.

LEAVES = LeafRegistry()

EMAIL_LEAF = LEAVES.register(
    Leaf(
        name="email_verified",
        label_active="Verify your email",
        label_done="Email verified",
        fix_url="/users/me/email/form",
        predicate=email_verified,
    )
)

CLINICIAN_VERIFIED_LEAF = LEAVES.register(
    Leaf(
        name="clinician_verified",
        label_active="Verify a clinician",
        label_done="Clinician verified",
        fix_url="/clinicians/form",
        predicate=clinician_verified,
    )
)

ORG_REP_ANY_LEAF = LEAVES.register(
    Leaf(
        name="org_rep_any",
        label_active="Verify your organization",
        label_done="Organization verified",
        fix_url="/organizations/form",
        predicate=any_org_rep_verified,
    )
)

OWNS_PROGRAM_LEAF = LEAVES.register(
    Leaf(
        name="owns_program",
        label_active="Add a program",
        label_done="Program added",
        fix_url="/programs/form",
        predicate=owns_program,
        # A user can't own a program until they're a verified rep for
        # that program's org (Program.create requires Claim B). Declaring
        # the dependency on the leaf means every capability that pulls
        # `owns_program` in via `evaluate_chain` gets `org_rep_any`
        # surfaced as a sibling step without each consumer re-listing it.
        requires=(ORG_REP_ANY_LEAF,),
    )
)

SUPERUSER_LEAF = LEAVES.register(
    Leaf(
        name="superuser",
        # Both label forms are nominal, not imperative — there is no
        # self-serve path to becoming a superuser, so the leaf never
        # renders as an actionable step. `fix_url` is empty for the same
        # reason; the requirements renderer shows a plain label when a
        # leaf carries no fix link.
        label_active="Superuser",
        label_done="Superuser",
        fix_url="",
        predicate=superuser,
    )
)


def _superuser_gate(user: Any, tree: Any) -> Any:
    """Wrap a capability's requirement tree in the superuser override.

    For a superuser the result is ``Gate(any of: <tree>, Superuser)`` —
    the capability detail page then shows *why* access is granted as an
    explicit "any one of these" branch. For everyone else the tree is
    returned unchanged: the override is an operational fact we don't
    advertise to users who don't hold it, so their requirement view
    stays exactly the real, actionable tree.
    """
    if not superuser(user):
        return tree
    return Gate(
        label_active=tree.label_active,
        label_done=tree.label_done,
        children=(tree, SUPERUSER_LEAF.evaluate(user)),
    )


def check_provider_identity(user: Any) -> CapabilityCheck:
    """Structured capability check for "the user has a verified provider
    identity" — a clinician (Claim A) or an org rep (Claim B), plus a
    verified email.

    Two surfaces share this gate:

    - **Read** — full-feed access (un-redacted provider details on the
      directory and feed). `can_act_as_provider` is the boolean form.
    - **Authored posts** — the `referral` and `clinician_opening`
      picker tiles on `/posts/form` (see `domain/templates/posts/
      form_new.html`). The picker is "coarse" — a Claim-B user
      without an affiliation passes the tile but still bounces at
      payload-authz time. Per-row payload authz lives in
      `_assert_post_payload_authz`; this check is for surfacing
      identity verification as the gating step in the picker UI.

    Tree: email_verified AND (clinician_verified OR org_rep_verified),
    OR'd with the superuser override for superusers (`_superuser_gate`).
    `ever_verified_at` retention is intentionally excluded — access
    reverts immediately when the underlying claim lapses.
    """
    return CapabilityCheck(
        name="provider-network",
        description="See full provider details and reach out directly.",
        tree=_superuser_gate(
            user,
            Bundle(
                label_active="Provider network",
                label_done="Provider network",
                children=(
                    EMAIL_LEAF.evaluate(user),
                    Gate(
                        label_active="Verify a clinician or organization",
                        label_done="Clinician or organization verified",
                        children=(
                            CLINICIAN_VERIFIED_LEAF.evaluate(user),
                            ORG_REP_ANY_LEAF.evaluate(user),
                        ),
                    ),
                ),
            ),
        ),
    )


def check_program_intake(user: Any) -> CapabilityCheck:
    """Structured capability check for publishing a program-intake post.

    Tree: email_verified AND any_org_rep_verified AND owns_a_program.
    Each conjunct corresponds to one Condition leaf with its own
    `fix_url`, so the user can see exactly which step is open and click
    straight into it. `ORG_REP_ANY_LEAF` is pulled in via
    `OWNS_PROGRAM_LEAF.requires` rather than listed inline — the
    dependency is declared once on the leaf.

    Per-row Claim B for the specific program's org is *not* enforced
    here — `_assert_post_payload_capability` (Phase 5) does that at
    create time against the chosen program. This check is the per-user
    "should the picker tile be lit" gate; the post payload hook is the
    per-row write gate.
    """
    return CapabilityCheck(
        name="program-intake",
        description="Publish a program intake on /posts/form.",
        tree=_superuser_gate(
            user,
            Bundle(
                label_active="Program intake",
                label_done="Program intake",
                children=(
                    EMAIL_LEAF.evaluate(user),
                    *OWNS_PROGRAM_LEAF.evaluate_chain(user),
                ),
            ),
        ),
    )


def check_superuser(user: Any) -> CapabilityCheck | None:
    """The superuser override as its own capability — visible ONLY to
    users who hold it.

    Returns ``None`` for everyone else, which the capability routes
    treat as "not applicable": omitted from the list page, 404 on the
    detail page. Superuser is an operational fact, not a step users can
    work toward, so advertising it to normal users would only confuse
    the requirements view.
    """
    if not superuser(user):
        return None
    return CapabilityCheck(
        name="superuser",
        description="Operational override — every capability is granted.",
        tree=Bundle(
            label_active="Superuser",
            label_done="Superuser",
            children=(SUPERUSER_LEAF.evaluate(user),),
        ),
    )


def can_post_program_intake_picker(user: Any) -> bool:
    """Picker-tile gate: the boolean form of `check_program_intake`.

    Symmetric with `can_act_as_provider` — both are the boolean form of
    the matching `check_*` for surfaces that only need granted/not
    (the picker tile, the locked-CTA branch). The superuser override is
    inside the check's tree (`_superuser_gate`), so no separate bypass
    is needed here. Per-row authorization on the post create payload
    stays with `can_post_program_intake(user, org)` and its caller in
    `_assert_post_payload_capability`.
    """
    return check_program_intake(user).granted


def can_act_as_provider(user: Any) -> bool:
    """Feed-teaser gate: the boolean form of `check_provider_identity`.

    Symmetric with `assert_can_act_as_provider` — the route-level guard
    and the template-level affordance read the same predicate, so they
    can't disagree about what a viewer sees. The superuser override is
    inside the check's tree (`_superuser_gate`) — superusers get full
    read access with the grant visible as an OR branch on the
    capability detail page, not via a side-channel bypass.
    """
    return check_provider_identity(user).granted


def assert_can_act_as_provider(user: Any) -> None:
    """Raising form of `can_act_as_provider`. Superuser bypass
    delegates to the predicate, which short-circuits first.

    Used as `ReadPolicy.assert_can_read` on entities whose data is
    restricted to verified network members (e.g. clinicians).
    """
    if not can_act_as_provider(user):
        from src.framework.http.exceptions import ForbiddenError

        raise ForbiddenError(detail="Provider network access required.")


# Pre-built `ReadPolicy` for the network gate. Specs that want
# "verified-clinician-or-org-rep can read; everyone else 403s and sees a
# locked-link popover" set `read_policy=VERIFIED_PROVIDER_READ_POLICY` rather
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
# domain facts (`assert_can_act_as_provider`, `can_act_as_provider`,
# `REASON_NOT_A_VERIFIED_PROVIDER`). A frozen instance is the cheapest binding
# that points all three at the same gate; a factory would just be
# `lambda: ReadPolicy(...)` over the same args, and a flag would push
# this domain-specific tuple into the framework which doesn't otherwise
# know about Claim A/B.
VERIFIED_PROVIDER_READ_POLICY: ReadPolicy = ReadPolicy(
    assert_can_read=assert_can_act_as_provider,
    can_read=can_act_as_provider,
    lock_reason=REASON_NOT_A_VERIFIED_PROVIDER,
)


def can_post_referral(user: Any) -> bool:
    """Self-path gate: posting a referral as the owning clinician requires
    Claim A (handoff §4.3) — or the superuser override. The org-rep
    authority path in `_assert_post_payload_authz` bypasses this check."""
    return superuser(user) or clinician_verified(user)


def can_post_opening(user: Any) -> bool:
    """Self-path gate: posting a clinician opening as the owning clinician
    requires Claim A (handoff §4.3) — or the superuser override. The
    org-rep authority path in `_assert_post_payload_authz` bypasses this
    check."""
    return superuser(user) or clinician_verified(user)


def can_message(user: Any) -> bool:
    """Responding/messaging requires Claim A (handoff §4.3) — or the
    superuser override. The messages cluster does not yet exist; the
    predicate is shipped so it can be wired into route handlers the
    moment that cluster lands."""
    return superuser(user) or clinician_verified(user)


def can_post_program_intake(user: Any, org: Any) -> bool:
    """Posting a program intake on behalf of an org requires Claim B for
    that org — or the superuser override."""
    return superuser(user) or org_rep_verified(user, org)


def can_post_org_referral(user: Any, org: Any, clinician: Any) -> bool:
    """Posting an org-attributed referral requires Claim B for the org
    AND the target clinician must have an active ClinicianAffiliation to
    the org (handoff §4.3 / §10.5) — or the superuser override."""
    if superuser(user):
        return True
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
    """Saving a favorite requires email verification only (handoff §4.3)
    — or the superuser override."""
    return superuser(user) or email_verified(user)


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
