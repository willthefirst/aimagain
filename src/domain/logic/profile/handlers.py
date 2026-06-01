"""Profile Hub mode dispatch.

`/profile` is one component with four modes per handoff §8.1: `setup`,
`manage`, `add-a-claim`, `re-verify`. Mode is a pure function of the
requesting user's `ClaimState` (no `User.setup_goals` column —
recomputed each load per the resolved design trade-off).

This handler returns the template context the `profile/hub.html`
component reads; the template branches on `mode` and includes the
matching partial. The mode constants are exposed so tests and the
template can use a single source of truth instead of magic strings.
"""

from __future__ import annotations

import logging
from typing import Any

from src.domain.logic import capabilities
from src.domain.models import User

logger = logging.getLogger(__name__)


MODE_SETUP = "setup"
MODE_MANAGE = "manage"
MODE_ADD_CLAIM = "add-a-claim"
MODE_REVERIFY = "re-verify"

PROFILE_MODES = (MODE_SETUP, MODE_MANAGE, MODE_ADD_CLAIM, MODE_REVERIFY)


def resolve_profile_mode(
    user: User,
    *,
    intent: str | None = None,
) -> str:
    """Pick the profile-hub mode from the user's current claim state.

    Rules (handoff §8.1):
    * No claim of either kind → `setup` (onboarding IS the hub in setup
      mode; no separate wizard).
    * Any lapsed claim → `re-verify` (one or more required attributes
      regressed; the affected claim's capabilities pause but read access
      is retained per `can_read_full_feed`).
    * Caller passes `intent='add_claim'` (from `/profile?intent=add_claim`
      after the user clicks "Add a capability") → `add-a-claim`.
    * Otherwise → `manage`.

    `intent` is sourced from the query string in the route handler. The
    Phase-5-skeleton ships `setup` + `manage` rendering only; the other
    two partials land in follow-up PRs (the predicate set already
    distinguishes them, and the mode here is stable across PRs).
    """
    state = capabilities.claim_state(user)
    if state.lapsed:
        return MODE_REVERIFY
    if not state.a and not state.b:
        return MODE_SETUP
    if intent == "add_claim":
        return MODE_ADD_CLAIM
    return MODE_MANAGE


def build_profile_context(
    user: User,
    *,
    intent: str | None = None,
) -> dict[str, Any]:
    """Compose the template context for `profile/hub.html`.

    Exposes the resolved mode + a snapshot of the `ClaimState` shape
    the partials read. The chrome scalars (`is_authenticated`,
    `claims`, `any_claim_lapsed`, etc.) are added by `base_context` at
    render time — this context only carries the hub-specific extras.
    """
    state = capabilities.claim_state(user)
    mode = resolve_profile_mode(user, intent=intent)
    logger.info(
        "profile.hub: user=%s mode=%s claim_a=%s claim_b=%d",
        user.id,
        mode,
        state.a,
        len(state.b),
    )
    return {
        "mode": mode,
        "profile_modes": PROFILE_MODES,
        "claim_state": state,
        "clinicians": list(getattr(user, "clinicians", None) or ()),
        "org_representations": list(getattr(user, "org_representations", None) or ()),
    }
