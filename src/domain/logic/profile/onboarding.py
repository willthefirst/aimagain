"""Declarative onboarding step registry.

The verification ladder a user climbs before they can post — email floor,
then identity (Claim A *or* Claim B) — expressed as an **ordered list of
steps** instead of a hardcoded if/elif chain. Each step declares the four
things every onboarding surface needs to render and act on it:

- `predicate(user)` — is this step already satisfied?
- `reason` — the closed-vocab `capabilities.REASON_*` code, which also
  yields the deep-link via `capabilities.fix_url_for(reason)`. The reason
  vocab stays the single home for "where do I go to fix this."
- `title` / `hint` — the checklist row label and the "what to do next"
  copy shown while the step is incomplete.
- `embed` — a presentation hint: `True` means a surface *may* render the
  satisfying form inline (the `/profile` orchestrator does this);
  `False` means link out. Advisory, not a routing decision.

Why a registry and not just `onboarding_readiness`: this is the backbone
the migration builds on (see RESOURCE_GRAMMAR.md and the profile-hub
plan). "Add a new verification requirement" becomes "append one
`OnboardingStep` row" — every consumer (the chrome banner, the `/profile`
checklist) re-renders without edits. The flat `onboarding_readiness`
projection in `view.py` answers the *compact* "can you post, and what's
the one next click" question; this registry answers the *itemized*
"what's done, what remains" question. They read the same `capabilities`
predicates, so they cannot disagree.

The two-claim OR (a user posts with Claim A *or* Claim B) is collapsed
into a single `identity` step whose predicate is "holds any posting-
capable claim." The clinician-vs-org *sub-paths* are the detailed guided
flow inside `/profile` (`profile/_setup.html`), not separate top-level
rows — same split the `/users/me` Verification card already makes
(Email / Identity). A future *required* verification is a new spine row;
a future *alternative way* to satisfy identity widens the predicate.

Pure projection, no I/O. Duck-typed via the `capabilities` predicates so
template stubs and the real `User` ORM row both work.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.domain.logic import capabilities


def _identity_verified(user: Any) -> bool:
    """Identity is satisfied by *either* posting-capable claim — a
    Verified Clinician (Claim A) or any verified org rep (Claim B). Mirror
    of `onboarding_readiness`'s `can_post = claim_a or claim_b`."""
    return capabilities.clinician_verified(user) or capabilities.any_org_rep_verified(
        user
    )


@dataclass(frozen=True)
class OnboardingStep:
    """One rung of the verification ladder. See module docstring."""

    key: str
    title: str
    hint: str
    reason: str
    predicate: Callable[[Any], bool]
    embed: bool

    def is_complete(self, user: Any) -> bool:
        return self.predicate(user)

    @property
    def action_href(self) -> str:
        """Deep-link into `/profile` that satisfies this step. Derived from
        `reason` so the URL vocab lives in `capabilities._FIX_URLS` only."""
        return capabilities.fix_url_for(self.reason)


# Ordered spine of required steps. Append a row to add a verification
# requirement; widen a predicate to add an alternative way to satisfy one.
ONBOARDING_STEPS: tuple[OnboardingStep, ...] = (
    OnboardingStep(
        key="email",
        title="Verify your email",
        hint="Confirm your email address to activate your account.",
        reason=capabilities.REASON_EMAIL_UNVERIFIED,
        predicate=capabilities.email_verified,
        embed=False,
    ),
    OnboardingStep(
        key="identity",
        title="Verify your identity",
        hint="Verify your clinician identity or your organization to start posting.",
        reason=capabilities.REASON_CLAIM_A_UNVERIFIED,
        predicate=_identity_verified,
        embed=True,
    ),
)


@dataclass(frozen=True)
class StepStatus:
    """A step paired with its computed completion for one user."""

    step: OnboardingStep
    complete: bool


@dataclass(frozen=True)
class OnboardingChecklist:
    """Itemized onboarding state for one user.

    - `statuses` — every spine step in order, each marked complete or not.
    - `next_step` — the first incomplete step (what to act on), or `None`.
    - `complete` — all spine steps satisfied; equivalently "can post."
    """

    statuses: tuple[StepStatus, ...]
    next_step: OnboardingStep | None
    complete: bool

    @property
    def incomplete(self) -> bool:
        return not self.complete


def onboarding_checklist(user: Any) -> OnboardingChecklist:
    """Project a user onto the ordered step registry.

    `complete` collapses to email AND (Claim A OR Claim B) — the same
    posting gate `onboarding_readiness.can_post` reports, by construction
    (both read the `capabilities` predicates)."""
    statuses = tuple(
        StepStatus(step=s, complete=s.is_complete(user)) for s in ONBOARDING_STEPS
    )
    next_step = next((s.step for s in statuses if not s.complete), None)
    return OnboardingChecklist(
        statuses=statuses,
        next_step=next_step,
        complete=next_step is None,
    )
