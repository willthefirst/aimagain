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


async def handle_clinician_create(
    *,
    first_name: str | None,
    last_name: str | None,
    npi: str | None,
    location_city: str,
    location_state: str,
    location_zip: str,
    requesting_user: User,
    clinician_repo: Any,
    organization_repo: Any,
    verification_repo: Any,
    audit_repo: Any,
) -> Any:
    """Create a minimal clinician profile from the profile hub and run
    NPI verification inline.

    Hardcodes ``solo_practice=True`` so the user doesn't need to pick
    an org during onboarding. Session/in_person defaults to "yes" via
    the schema. The caller returns ``HX-Redirect: /profile`` so the hub
    re-renders with the new clinician's NPPES state already reflected.
    """
    from src.domain.logic.clinicians.handlers import (
        _assert_clinician_payload_org_ownership,
        after_create_clinician_verification,
    )
    from src.domain.logic.clinicians.schema import ClinicianCreate
    from src.domain.models import Clinician

    payload = ClinicianCreate(
        first_name=first_name,
        last_name=last_name,
        npi=npi,
        solo_practice=True,
        location_city=location_city,
        location_state=location_state,
        location_zip=location_zip,
    )

    await _assert_clinician_payload_org_ownership(
        payload=payload,
        requesting_user=requesting_user,
        organization_repo=organization_repo,
    )

    clinician = Clinician(
        owner_id=requesting_user.id,
        **payload.model_dump(),
    )
    clinician = await clinician_repo.create(clinician)

    await after_create_clinician_verification(
        row=clinician,
        payload=payload,
        requesting_user=requesting_user,
        verification_repo=verification_repo,
        clinician_repo=clinician_repo,
        verification_audit_repo=audit_repo,
    )
    return clinician


async def handle_clinician_license_create(
    *,
    clinician_id: UUID,
    license_type: str,
    license_number: str,
    issuing_state: str,
    expiration_date: str | None,
    requesting_user: User,
    clinician_repo: Any,
    verification_repo: Any,
    audit_repo: Any,
) -> Any:
    """Create a licensure for an onboarding clinician and immediately
    attest it as active in one step.

    Delegates attestation to ``handle_set_license_attestation`` which
    owns the audit trail and Claim-A cache recompute. The caller returns
    ``HX-Redirect: /profile`` so the hub re-renders with Claim A
    potentially unlocked.
    """
    from datetime import date

    from src.domain.logic.clinicians.handlers import handle_set_license_attestation
    from src.domain.logic.clinicians.schema import ClinicianLicensureCreate
    from src.domain.models import Clinician, ClinicianLicensure
    from src.framework.authz import is_owner_or_admin
    from src.framework.http.exceptions import ForbiddenError, NotFoundError

    clinician = await clinician_repo.get_by_model_id(Clinician, clinician_id)
    if clinician is None:
        raise NotFoundError(detail="Clinician not found")
    if not is_owner_or_admin(clinician, requesting_user):
        raise ForbiddenError(detail="Cannot add licenses for this clinician")

    parsed_expiry = date.fromisoformat(expiration_date) if expiration_date else None

    licensure_payload = ClinicianLicensureCreate(
        license_type=license_type,
        license_number=license_number,
        issuing_state=issuing_state,
        expiration_date=parsed_expiry,
    )
    licensure = ClinicianLicensure(
        clinician_id=clinician_id,
        **licensure_payload.model_dump(),
    )
    licensure = await clinician_repo.create(licensure)

    # Attest immediately — the form's checkbox confirms user consent.
    from pydantic import BaseModel as _BaseModel

    class _AttestPayload(_BaseModel):
        attested: bool = True

    return await handle_set_license_attestation(
        clinician_id=clinician_id,
        licensure_id=licensure.id,
        payload=_AttestPayload(),
        repo=clinician_repo,
        verification_repo=verification_repo,
        audit_repo=audit_repo,
        requesting_user=requesting_user,
    )
