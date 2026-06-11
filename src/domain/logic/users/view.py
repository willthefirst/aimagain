"""Onboarding readiness projection for the users domain.

`onboarding_readiness(user)` collapses the two-claim verification model
into one capability-accurate summary of "what does this user still need
to do before they can post." It exists so any surface that *reports*
verification status — the read-only Verification card on `/users/me` —
reads the *same* readiness from the *same* predicates the server-side
post gate uses (`capabilities.*`). That's the whole point of the
capabilities module: a status signpost can't disagree with the gate.

This is a pure projection (no I/O): it reads already-loaded relationships
off `user` via the `capabilities` predicates and returns a frozen view
object. Mirror of `clinician_card_view` / `post_card_view`; exposed as a
Jinja global in `template_globals.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.domain.logic import capabilities


@dataclass(frozen=True)
class OnboardingReadiness:
    """Compact readiness summary for onboarding surfaces.

    - `email_verified` — the floor for every claim.
    - `claim_a_verified` — a Verified Clinician (`clinician_verified`).
    - `claim_b_verified` — a verified org rep for ≥1 org
      (`any_org_rep_verified`).
    - `can_post` — holds at least one posting-capable claim (A or B). The
      gate a "Post an opening / referral" CTA must respect.
    - `can_act_as_provider` — full (un-teased) feed access.
    - `next_label` / `next_href` — the single next verification step, or
      ``None`` when nothing remains (the user can post). Hrefs come from
      `capabilities.fix_url_for` (the step subroutes) so the deep-link
      vocab stays in one place.
    """

    email_verified: bool
    claim_a_verified: bool
    claim_b_verified: bool
    can_post: bool
    can_act_as_provider: bool
    next_label: str | None
    next_href: str | None


def onboarding_readiness(user: Any) -> OnboardingReadiness:
    """Project a user's claim state into an onboarding readiness summary.

    Pure function over the `capabilities` predicates — duck-typed via
    `getattr` like the rest of that module, so template stubs and the
    real `User` ORM row both work. `can_post` is "holds a posting-capable
    claim" (Claim A or any verified Claim B), matching the structure of
    `can_act_as_provider`; the per-kind gates (`can_post_referral`,
    `can_post_program_intake`) refine it at the actual post boundary.
    """
    email = capabilities.email_verified(user)
    claim_a = capabilities.clinician_verified(user)
    claim_b = capabilities.any_org_rep_verified(user)
    can_post = claim_a or claim_b

    next_label: str | None
    next_href: str | None
    if not email:
        next_label = "Verify your email"
        next_href = capabilities.fix_url_for(capabilities.REASON_EMAIL_UNVERIFIED)
    elif not can_post:
        next_label = "Verify your identity to start posting"
        next_href = "/users/me"
    else:
        next_label = None
        next_href = None

    return OnboardingReadiness(
        email_verified=email,
        claim_a_verified=claim_a,
        claim_b_verified=claim_b,
        can_post=can_post,
        can_act_as_provider=capabilities.can_act_as_provider(user),
        next_label=next_label,
        next_href=next_href,
    )
