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
from uuid import UUID

from src.domain.logic import capabilities
from src.domain.logic.profile.onboarding import onboarding_checklist
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


def _user_is_demo_context(user: User) -> bool:
    """Return True if the user is associated with any demo organization.

    Checks both org representations (Claim B links) and directly owned
    organizations — both relationships are selectin-loaded on User, so
    this is free after the initial user fetch.
    """
    for rep in getattr(user, "org_representations", None) or ():
        org = getattr(rep, "org", None)
        if org and getattr(org, "is_demo", False):
            return True
    for org in getattr(user, "organizations", None) or ():
        if getattr(org, "is_demo", False):
            return True
    return False


def build_profile_context(
    user: User,
    *,
    intent: str | None = None,
) -> dict[str, Any]:
    """Compose the template context for `profile/hub.html`.

    Exposes the resolved mode + a snapshot of the `ClaimState` shape
    the partials read, plus the `onboarding_checklist` projection that
    drives the registry-driven progress overview (`_checklist.html`).
    The checklist reads the same `capabilities` predicates as the post
    gate and the global banner, so the three can't disagree. The chrome
    scalars (`is_authenticated`, `claims`, `any_claim_lapsed`, etc.) are
    added by `base_context` at render time — this context only carries
    the hub-specific extras.
    """
    state = capabilities.claim_state(user)
    mode = resolve_profile_mode(user, intent=intent)
    is_demo_context = _user_is_demo_context(user)
    logger.info(
        "profile.hub: user=%s mode=%s claim_a=%s claim_b=%d demo=%s",
        user.id,
        mode,
        state.a,
        len(state.b),
        is_demo_context,
    )
    return {
        "mode": mode,
        "profile_modes": PROFILE_MODES,
        "claim_state": state,
        "checklist": onboarding_checklist(user),
        "clinicians": list(getattr(user, "clinicians", None) or ()),
        "org_representations": list(getattr(user, "org_representations", None) or ()),
        "is_demo_context": is_demo_context,
    }


async def handle_clinician_details_update(
    *,
    clinician_id: UUID,
    location_city: str | None,
    location_state: str | None,
    location_zip: str | None,
    in_person_sessions: str | None,
    virtual_sessions: str | None,
    accepts_out_of_network: bool | None,
    sliding_scale: bool | None,
    cost: str | None,
    requesting_user: User,
    clinician_repo: Any,
    audit_repo: Any,
) -> Any:
    """Patch a clinician's practice details (location / availability /
    insurance) from the profile hub's "complete your profile" section.
    Only non-None fields are written; the call is a no-op if all args
    are None.
    """
    from src.domain.models import Clinician
    from src.domain.specs.clinician import CLINICIAN_ENTITY
    from src.framework.audit.core import mutate
    from src.framework.authz import is_owner_or_admin
    from src.framework.http.exceptions import ForbiddenError, NotFoundError

    clinician = await clinician_repo.get_by_model_id(Clinician, clinician_id)
    if clinician is None:
        raise NotFoundError(detail="Clinician not found")
    if not is_owner_or_admin(clinician, requesting_user):
        raise ForbiddenError(detail="Cannot update this clinician")

    fields: dict[str, Any] = {}
    # Location: patch all three or none — partial location is not useful.
    if (
        location_city is not None
        and location_state is not None
        and location_zip is not None
    ):
        fields["location_city"] = location_city or None
        fields["location_state"] = location_state or None
        fields["location_zip"] = location_zip or None
    if in_person_sessions is not None:
        fields["in_person_sessions"] = in_person_sessions
    if virtual_sessions is not None:
        fields["virtual_sessions"] = virtual_sessions
    if accepts_out_of_network is not None:
        fields["accepts_out_of_network"] = accepts_out_of_network
    if sliding_scale is not None:
        fields["sliding_scale"] = sliding_scale
    if cost is not None:
        fields["cost"] = cost or None

    if fields:
        async with mutate(
            clinician_repo,
            audit_repo,
            actor=requesting_user,
            target=clinician,
            resource=CLINICIAN_ENTITY.audit,
            verb="update",
        ):
            await clinician_repo.patch(clinician, **fields)
    return clinician
