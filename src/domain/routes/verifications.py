"""Bespoke router for the verification-related endpoints.

`Verification` has no EntitySpec — there's no public CRUD surface.
This file hosts:

- the admin-only manual retrigger (POST /clinicians/{id}/verifications)
- the end-user NPI submit endpoints (POST /clinicians/{id}/npi and
  POST /organizations/{id}/npi) the Profile Hub's `_claim_a_card` /
  `_claim_b_card` POST against. Setting the NPI here calls NPPES
  synchronously and writes the resolved state through to
  `npi_match_status` (`matched` / `mismatch` / `none`) before the
  response returns — no worker, no polling, no "Verifying…" pending
  state for the UI to follow up on.

The bespoke shape follows `auth_pages` / `favorites` (see
`src/domain/routes/README.md` § "Bespoke routes"); wired into
`src/main.py` alongside the other hand-rolled routers.

Submit-endpoint authz: the requesting user must own the target
Clinician/Organization (or be a superuser). This matches the
existing CRUD authz on those entities — the submit endpoint is a
narrower verb on the same resource.
"""

from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, field_validator

from src.auth_config import current_active_user, current_admin_user
from src.domain.logic.clinicians.repository import (
    ClinicianRepository,
    get_clinician_repository,
)
from src.domain.logic.organizations.repository import (
    OrganizationRepository,
    get_organization_repository,
)
from src.domain.logic.verifications.events import record_verification_event
from src.domain.logic.verifications.handlers import (
    HTTP_TIMEOUT_SECONDS,
    handle_create_clinician_verification,
    run_clinician_verification,
    run_org_demo_verification,
    run_org_verification,
)
from src.domain.logic.verifications.repository import (
    VerificationRepository,
    get_verification_repository,
)
from src.domain.models import Clinician, Organization, User
from src.framework.audit.repository import AuditRepository
from src.framework.authz import is_owner_or_admin
from src.framework.http.exceptions import (
    ForbiddenError,
    NotFoundError,
)
from src.framework.http.responses import refreshed_response
from src.framework.persistence.dependencies import get_audit_repository

verifications_api_router = APIRouter(tags=["Verifications"])

_DEMO_OUTCOMES = ("verified", "needs_review", "failed")


class NpiSubmitBody(BaseModel):
    """Wire shape for the inline NPI submit endpoints. The 10-digit
    GLOB constraint also lives on the DB column; pinning it here too
    means a malformed value fails with a Pydantic 422 before the DB
    layer ever sees it (better error message + no DB round-trip).

    `demo_outcome` is optional and only honored when the target entity
    has `is_demo=True`; ignored for real organizations."""

    npi: str
    demo_outcome: Literal["verified", "needs_review", "failed"] | None = None

    @field_validator("npi")
    @classmethod
    def _ten_digits(cls, value: str) -> str:
        stripped = value.strip()
        if not (len(stripped) == 10 and stripped.isdigit()):
            raise ValueError("npi must be exactly 10 digits")
        return stripped


@verifications_api_router.post(
    "/clinicians/{clinician_id}/verifications",
    status_code=status.HTTP_201_CREATED,
    name="verifications:create",
)
async def create_clinician_verification(
    clinician_id: UUID,
    response: Response,
    verification_repo: VerificationRepository = Depends(get_verification_repository),
    clinician_repo: ClinicianRepository = Depends(get_clinician_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    requesting_user: User = Depends(current_admin_user),
) -> dict[str, str]:
    """Admin-only manual retrigger. See
    `src/domain/logic/verifications/handlers.py` for the orchestration."""
    verification = await handle_create_clinician_verification(
        clinician_id=clinician_id,
        verification_repo=verification_repo,
        clinician_repo=clinician_repo,
        audit_repo=audit_repo,
        requesting_user=requesting_user,
    )
    response.headers["Location"] = (
        f"/clinicians/{clinician_id}/verifications/{verification.id}"
    )
    return {"id": str(verification.id), "status": verification.status}


@verifications_api_router.post(
    "/clinicians/{clinician_id}/npi",
    status_code=status.HTTP_200_OK,
    name="verifications:clinician_npi_submit",
)
async def submit_clinician_npi(
    clinician_id: UUID,
    body: NpiSubmitBody,
    clinician_repo: ClinicianRepository = Depends(get_clinician_repository),
    verification_repo: VerificationRepository = Depends(get_verification_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    requesting_user: User = Depends(current_active_user),
) -> Response:
    """User-driven Type-1 NPI submission. Synchronous:

    1. Persist `Clinician.npi`.
    2. Append a `Verification` event of type `npi_submitted` (the
       user-action log entry — distinct from the NPPES-result event
       the pipeline writes next).
    3. Run `run_clinician_verification(...)` inline — calls NPPES,
       writes a second `Verification` row (`npi_resolved`), and flips
       `npi_match_status` to its final state (`matched` /
       `mismatch` / `none`) in the same transaction.

    By the time the response returns, the row is settled. The Profile
    Hub renders the resolved state directly — no polling, no
    intermediate "Verifying…" pill.

    Authz: the requesting user must own the clinician (or be admin).
    """
    clinician = await clinician_repo.get_by_model_id(Clinician, clinician_id)
    if clinician is None:
        raise NotFoundError(detail="Clinician not found")
    if not is_owner_or_admin(clinician, requesting_user):
        raise ForbiddenError(detail="Cannot submit NPI for this clinician")

    clinician.npi = body.npi
    await record_verification_event(
        verification_repo=verification_repo,
        audit_repo=audit_repo,
        subject_type="clinician",
        clinician_id=clinician.id,
        event_type="npi_submitted",
        status="needs_review",
        evidence={"npi": body.npi},
        actor_id=requesting_user.id,
    )
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
        await run_clinician_verification(
            clinician_id=clinician.id,
            verification_repo=verification_repo,
            clinician_repo=clinician_repo,
            audit_repo=audit_repo,
            http=http,
            actor_id=requesting_user.id,
        )
    return refreshed_response()


@verifications_api_router.post(
    "/organizations/{organization_id}/npi",
    status_code=status.HTTP_200_OK,
    name="verifications:org_npi_submit",
)
async def submit_organization_npi(
    organization_id: UUID,
    body: NpiSubmitBody,
    org_repo: OrganizationRepository = Depends(get_organization_repository),
    verification_repo: VerificationRepository = Depends(get_verification_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    requesting_user: User = Depends(current_active_user),
) -> Response:
    """User-driven Type-2 (organizational) NPI submission. Mirror of
    `submit_clinician_npi` for Claim B — synchronous: NPPES runs
    inline and the row is settled before the response returns. The
    org's Type-2 NPI is verified once per Organization (handoff §6) —
    subsequent representatives prove authority through
    `OrgRepresentation`, not by re-submitting the NPI.

    When `org.is_demo` is True and `body.demo_outcome` is set, NPPES is
    bypassed and the selected outcome is persisted directly."""
    org = await org_repo.get_by_model_id(Organization, organization_id)
    if org is None:
        raise NotFoundError(detail="Organization not found")
    if not is_owner_or_admin(org, requesting_user):
        raise ForbiddenError(detail="Cannot submit NPI for this organization")

    org.npi = body.npi
    await record_verification_event(
        verification_repo=verification_repo,
        audit_repo=audit_repo,
        subject_type="organization",
        org_id=org.id,
        event_type="npi_submitted",
        status="needs_review",
        evidence={"npi": body.npi},
        actor_id=requesting_user.id,
    )

    if org.is_demo and body.demo_outcome:
        await run_org_demo_verification(
            org_id=org.id,
            demo_outcome=body.demo_outcome,
            verification_repo=verification_repo,
            org_repo=org_repo,
            audit_repo=audit_repo,
            actor_id=requesting_user.id,
        )
    else:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
            await run_org_verification(
                org_id=org.id,
                verification_repo=verification_repo,
                org_repo=org_repo,
                audit_repo=audit_repo,
                http=http,
                actor_id=requesting_user.id,
            )
    return refreshed_response()


# Note on license attestation: previously a bespoke POST endpoint here;
# now a state axis on `LICENSURE_ENTITY`
# (`PUT /clinicians/{clinician_id}/licensures/{licensure_id}/attestation`).
# The framework's `mount_state_axis` gained parent-owned-subentity
# support in PR #1082 so this no longer needs to be hand-rolled. Handler
# at `src.domain.logic.clinicians.handlers.handle_set_license_attestation`.
