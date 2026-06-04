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
  that's already complete redirects back to the hub.

`GET /profile/identity` is a **dispatching picker** (issue #1166): a
read-only view whose two cards link *out* to the canonical create forms
that own the work — `/clinicians/form` and `/organizations/form`. Those
forms run NPI verification and grant the owner `OrgRepresentation`
themselves (see `CLINICIAN_ENTITY` / `ORGANIZATION_ENTITY`), so the
identity step hosts no create form of its own — read xor form. The
post-create steps (NPI re-verify on mismatch, license attestation) live
on the clinician's own canonical pages, reached from there.

`POST /profile/clinician/{id}/details` remains: it's the manage-mode
"complete your profile" patch, not part of the identity step.

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
from src.domain.logic.profile.handlers import (
    build_profile_context,
    handle_clinician_details_update,
)
from src.domain.logic.profile.onboarding import ONBOARDING_STEPS
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


@profile_pages_router.get("/profile/{step}", name="profile:step")
async def profile_step(
    step: str,
    request: Request,
    requesting_user: User = Depends(current_active_user),
) -> Any:
    """Render one onboarding step's action page — the subroute the
    `/profile` table of contents links to.

    `step` is a key in the `ONBOARDING_STEPS` registry (404 otherwise);
    the page satisfies that step (email → resend, identity → the
    dispatching picker that links to the canonical clinician / org create
    forms).

    A step that's already complete has nothing to act on, so it redirects
    to the hub — which is also how a user lands back on the table of
    contents once they finish a step elsewhere.
    """
    onboarding_step = next((s for s in ONBOARDING_STEPS if s.key == step), None)
    if onboarding_step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    context = build_profile_context(requesting_user)
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
