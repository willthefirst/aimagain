"""Bespoke router for the Profile Hub (`/profile`).

The hub is one component with four modes — setup / manage / add-a-claim
/ re-verify — and onboarding IS this hub in setup mode (no separate
wizard). Mode is a pure function of the requesting user's claim state;
see `src.domain.logic.profile.handlers.resolve_profile_mode`.

In setup mode the hub is a **table of contents**: it lists the
onboarding steps (from the `ONBOARDING_STEPS` registry) and links each
to its own subroute, where the satisfying form lives:

- ``GET /profile/{step}`` — one registry-driven handler renders the step
  named by `{step}` (e.g. `/profile/email`, `/profile/identity`). A step
  that's already complete redirects back to the hub, so a form submit
  (which bounces back to its step) lands on the table of contents once
  the step is done.

The onboarding POST endpoints redirect back to the relevant step page
(not the hub) so a multi-stage step — identity is NPI then license —
flows on one page:

- ``POST /profile/clinician`` — create a minimal clinician + run NPI
  verification inline, then return to ``/profile/identity``.
- ``POST /profile/clinician/{clinician_id}/license`` — create a
  licensure and attest it in one step, then return to ``/profile/identity``.

The hub is intentionally **not** mounted as a generic EntitySpec: it's
not a CRUD resource (no id in the URL, no list/detail surface), and
overloading the `/users/{id}` detail page with mode-dispatch would
make the user entity ungeneric. The bespoke shape matches
`auth_pages` / `verifications` (see `routes/README.md` § "Bespoke
routes").
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from src.auth_config import current_active_user
from src.domain.logic.clinicians.repository import (
    ClinicianRepository,
    get_clinician_repository,
)
from src.domain.logic.org_representations.repository import (
    OrgRepresentationRepository,
    get_org_representation_repository,
)
from src.domain.logic.organizations.repository import (
    OrganizationRepository,
    get_organization_repository,
)
from src.domain.logic.profile.handlers import (
    build_profile_context,
    handle_clinician_create,
    handle_clinician_details_update,
    handle_clinician_identity_update,
    handle_clinician_license_create,
    handle_org_create,
)
from src.domain.logic.profile.onboarding import ONBOARDING_STEPS
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
    path: str | None = None,
) -> Any:
    """Render the profile hub. `intent=add_claim` (set by the
    "Add a capability" CTA) lands the user in `add-a-claim` mode when
    they already hold at least one claim; otherwise mode is derived
    purely from the claim state.

    `path=clinician|org` (set by the setup-mode persona chooser) selects
    which onboarding sub-flow the setup partial renders for a fresh user;
    it is ignored once the user has started a claim (the started path is
    implied by what they created). See `resolve_setup_path`.
    """
    context = build_profile_context(requesting_user, intent=intent, path_hint=path)
    return APIResponse.html_response(
        "profile/hub.html",
        context,
        request,
        current_user=requesting_user,
    )


@profile_pages_router.get("/profile/{step}", name="profile:step")
async def profile_step(
    step: str,
    request: Request,
    requesting_user: User = Depends(current_active_user),
    path: str | None = None,
) -> Any:
    """Render one onboarding step's action page — the subroute the
    `/profile` table of contents links to.

    `step` is a key in the `ONBOARDING_STEPS` registry (404 otherwise);
    the page hosts the form that satisfies that step (email → resend,
    identity → the guided setup flow). `path=clinician|org` is forwarded
    to the identity setup flow exactly as on the hub.

    A step that's already complete has nothing to act on, so it redirects
    to the hub. That's also what returns the user to the table of contents
    once they finish a step whose POST bounced them back here.
    """
    onboarding_step = next((s for s in ONBOARDING_STEPS if s.key == step), None)
    if onboarding_step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    context = build_profile_context(requesting_user, path_hint=path)
    step_status = next(s for s in context["checklist"].statuses if s.step.key == step)
    if step_status.complete:
        return RedirectResponse("/profile", status_code=status.HTTP_303_SEE_OTHER)
    context["step"] = onboarding_step
    return APIResponse.html_response(
        "profile/step.html",
        context,
        request,
        current_user=requesting_user,
    )


@profile_pages_router.post("/profile/clinician", name="profile:clinician_create")
async def profile_clinician_create(
    first_name: str | None = Form(default=None),
    last_name: str | None = Form(default=None),
    npi: str | None = Form(default=None),
    practice_name: str | None = Form(default=None),
    location_city: str | None = Form(default=None),
    location_state: str | None = Form(default=None),
    location_zip: str | None = Form(default=None),
    demo_outcome: str | None = Form(default=None),
    requesting_user: User = Depends(current_active_user),
    clinician_repo: ClinicianRepository = Depends(get_clinician_repository),
    organization_repo: OrganizationRepository = Depends(get_organization_repository),
    org_rep_repo: OrgRepresentationRepository = Depends(
        get_org_representation_repository
    ),
    verification_repo: VerificationRepository = Depends(get_verification_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
) -> Any:
    """Create a minimal clinician profile from the onboarding hub.

    Fires NPI verification inline then redirects back to /profile/identity
    so the identity step re-renders with the NPPES result reflected (and,
    once the step is fully verified, on to the hub table of contents).
    Also auto-creates an OrgRepresentation for the solo-practice org
    so the user has owner authority over their practice immediately.

    `practice_name` names the auto-created org (falls back to "first last"
    then username). `demo_outcome` is only honored in demo org context.
    """
    await handle_clinician_create(
        first_name=first_name,
        last_name=last_name,
        npi=npi,
        practice_name=practice_name,
        location_city=location_city,
        location_state=location_state,
        location_zip=location_zip,
        requesting_user=requesting_user,
        clinician_repo=clinician_repo,
        organization_repo=organization_repo,
        org_rep_repo=org_rep_repo,
        verification_repo=verification_repo,
        audit_repo=audit_repo,
        demo_outcome=demo_outcome,
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={},
        headers={"HX-Redirect": "/profile/identity"},
    )


@profile_pages_router.post("/profile/org", name="profile:org_create")
async def profile_org_create(
    org_name: str = Form(...),
    org_type: str = Form(...),
    org_npi: str | None = Form(default=None),
    requesting_user: User = Depends(current_active_user),
    organization_repo: OrganizationRepository = Depends(get_organization_repository),
    org_rep_repo: OrgRepresentationRepository = Depends(
        get_org_representation_repository
    ),
    verification_repo: VerificationRepository = Depends(get_verification_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
) -> Any:
    """Register an organization and auto-grant the submitting user owner
    authority over it.

    For non-clinician org reps this is the primary onboarding path — they
    skip the NPI / license steps and land here directly. Clinicians can
    also use this to register a named practice separate from their
    solo-practice auto-org (e.g. after joining a group practice).

    If ``org_npi`` is provided the org NPPES verification runs inline,
    exactly as clinician NPI verification does. ``org_verified`` stays
    ``False`` if no NPI is given; the user can add one later from the
    manage view.
    """
    await handle_org_create(
        org_name=org_name,
        org_type=org_type,
        org_npi=org_npi or None,
        requesting_user=requesting_user,
        organization_repo=organization_repo,
        org_rep_repo=org_rep_repo,
        verification_repo=verification_repo,
        audit_repo=audit_repo,
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={},
        headers={"HX-Redirect": "/profile/identity"},
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
    checkbox on the same form. Returns to /profile/identity, which redirects
    on to the hub once the identity step is fully satisfied.
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
        headers={"HX-Redirect": "/profile/identity"},
    )


@profile_pages_router.post(
    "/profile/clinician/{clinician_id}/identity",
    name="profile:clinician_identity_update",
)
async def profile_clinician_identity_update(
    clinician_id: UUID,
    first_name: str | None = Form(default=None),
    last_name: str | None = Form(default=None),
    npi: str | None = Form(default=None),
    demo_outcome: str | None = Form(default=None),
    requesting_user: User = Depends(current_active_user),
    clinician_repo: ClinicianRepository = Depends(get_clinician_repository),
    verification_repo: VerificationRepository = Depends(get_verification_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
) -> Any:
    """Update a clinician's name + NPI and immediately re-run NPI
    verification.  Presented as a form on the /profile/identity step when
    the initial verification returned a mismatch — keeps the user on the
    identity step rather than bouncing them to the full clinician-edit page.

    `demo_outcome` is only honored when the requesting user is in a demo
    org context.
    """
    await handle_clinician_identity_update(
        clinician_id=clinician_id,
        first_name=first_name,
        last_name=last_name,
        npi=npi,
        requesting_user=requesting_user,
        clinician_repo=clinician_repo,
        verification_repo=verification_repo,
        audit_repo=audit_repo,
        demo_outcome=demo_outcome,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={},
        headers={"HX-Redirect": "/profile/identity"},
    )


@profile_pages_router.post(
    "/profile/clinician/{clinician_id}/details",
    name="profile:clinician_details_update",
)
async def profile_clinician_details_update(
    clinician_id: UUID,
    location_city: str | None = Form(default=None),
    location_state: str | None = Form(default=None),
    location_zip: str | None = Form(default=None),
    in_person_sessions: str | None = Form(default=None),
    virtual_sessions: str | None = Form(default=None),
    accepts_out_of_network: bool | None = Form(default=None),
    sliding_scale: bool | None = Form(default=None),
    cost: str | None = Form(default=None),
    requesting_user: User = Depends(current_active_user),
    clinician_repo: ClinicianRepository = Depends(get_clinician_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
) -> Any:
    """Patch a clinician's location / availability / insurance from the
    profile hub's "complete your profile" section.  Returns the user to
    /profile after saving so the hub reflects the updated state.
    """
    await handle_clinician_details_update(
        clinician_id=clinician_id,
        location_city=location_city,
        location_state=location_state,
        location_zip=location_zip,
        in_person_sessions=in_person_sessions,
        virtual_sessions=virtual_sessions,
        accepts_out_of_network=accepts_out_of_network,
        sliding_scale=sliding_scale,
        cost=cost,
        requesting_user=requesting_user,
        clinician_repo=clinician_repo,
        audit_repo=audit_repo,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={},
        headers={"HX-Redirect": "/profile"},
    )
