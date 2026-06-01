"""Bespoke router for the Profile Hub (`/profile`).

The hub is one component with four modes — setup / manage / add-a-claim
/ re-verify — and onboarding IS this hub in setup mode (no separate
wizard). Mode is a pure function of the requesting user's claim state;
see `src.domain.logic.profile.handlers.resolve_profile_mode`.

In addition to the hub GET, this router owns two onboarding POST
endpoints that stay on `/profile` after completion (rather than
redirecting to entity-specific pages):

- ``POST /profile/clinician`` — create a minimal clinician + run NPI
  verification inline, then return to the hub.
- ``POST /profile/clinician/{clinician_id}/license`` — create a
  licensure and attest it in one step, then return to the hub.

The hub is intentionally **not** mounted as a generic EntitySpec: it's
not a CRUD resource (no id in the URL, no list/detail surface), and
overloading the `/users/{id}` detail page with mode-dispatch would
make the user entity ungeneric. The bespoke shape matches
`auth_pages` / `verifications` (see `routes/README.md` § "Bespoke
routes").
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import JSONResponse

from src.auth_config import current_active_user
from src.domain.logic.clinicians.repository import (
    ClinicianRepository,
    get_clinician_repository,
)
from src.domain.logic.organizations.repository import (
    OrganizationRepository,
    get_organization_repository,
)
from src.domain.logic.profile.handlers import (
    build_profile_context,
    handle_clinician_create,
    handle_clinician_license_create,
)
from src.domain.logic.verifications.repository import (
    VerificationRepository,
    get_verification_repository,
)
from src.domain.models import User
from src.framework.audit.repository import AuditRepository
from src.framework.http.responses import APIResponse
from src.framework.persistence.dependencies import get_audit_repository

profile_pages_router = APIRouter(tags=["Profile"])


@profile_pages_router.get("/profile", name="profile:hub")
async def profile_hub(
    request: Request,
    requesting_user: User = Depends(current_active_user),
    intent: str | None = None,
) -> Any:
    """Render the profile hub. `intent=add_claim` (set by the
    "Add a capability" CTA) lands the user in `add-a-claim` mode when
    they already hold at least one claim; otherwise mode is derived
    purely from the claim state.
    """
    context = build_profile_context(requesting_user, intent=intent)
    return APIResponse.html_response(
        "profile/hub.html",
        context,
        request,
        current_user=requesting_user,
    )


@profile_pages_router.post("/profile/clinician", name="profile:clinician_create")
async def profile_clinician_create(
    first_name: str | None = Form(default=None),
    last_name: str | None = Form(default=None),
    npi: str | None = Form(default=None),
    location_city: str = Form(...),
    location_state: str = Form(...),
    location_zip: str = Form(...),
    requesting_user: User = Depends(current_active_user),
    clinician_repo: ClinicianRepository = Depends(get_clinician_repository),
    organization_repo: OrganizationRepository = Depends(get_organization_repository),
    verification_repo: VerificationRepository = Depends(get_verification_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
) -> Any:
    """Create a minimal clinician profile from the onboarding hub.

    Fires NPI verification inline (same as the generic clinician
    create) then redirects back to /profile so the hub re-renders
    with the NPPES result already reflected in the setup flow.
    """
    await handle_clinician_create(
        first_name=first_name,
        last_name=last_name,
        npi=npi,
        location_city=location_city,
        location_state=location_state,
        location_zip=location_zip,
        requesting_user=requesting_user,
        clinician_repo=clinician_repo,
        organization_repo=organization_repo,
        verification_repo=verification_repo,
        audit_repo=audit_repo,
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={},
        headers={"HX-Redirect": "/profile"},
    )


@profile_pages_router.post(
    "/profile/clinician/{clinician_id}/license",
    name="profile:clinician_license_create",
)
async def profile_clinician_license_create(
    clinician_id: UUID,
    license_type: str = Form(...),
    license_number: str = Form(...),
    issuing_state: str = Form(...),
    expiration_date: str | None = Form(default=None),
    requesting_user: User = Depends(current_active_user),
    clinician_repo: ClinicianRepository = Depends(get_clinician_repository),
    verification_repo: VerificationRepository = Depends(get_verification_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
) -> Any:
    """Create a licensure and attest it in one step from the onboarding hub.

    Combining create + attest removes the two-step dance (add license,
    then separately attest) by requiring the user to check an attestation
    checkbox on the same form. Returns to /profile so the hub shows the
    updated Claim A state.
    """
    await handle_clinician_license_create(
        clinician_id=clinician_id,
        license_type=license_type,
        license_number=license_number,
        issuing_state=issuing_state,
        expiration_date=expiration_date or None,
        requesting_user=requesting_user,
        clinician_repo=clinician_repo,
        verification_repo=verification_repo,
        audit_repo=audit_repo,
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={},
        headers={"HX-Redirect": "/profile"},
    )
