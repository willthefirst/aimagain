"""Bespoke router for the /welcome onboarding wizard.

Pattern: every step is a `GET /welcome/<step>` page + `POST /welcome/<step>`
shim. The shim validates → calls a service function → redirects via
`next_step()`. On validation error the form fragment is re-rendered with
errors inline.

This router is intentionally thin — all business logic lives in
`src/domain/logic/onboarding/`.

Modeled on `src/domain/routes/auth_pages.py`.
"""

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth_config import current_active_user
from src.db import get_db_session
from src.domain.logic.onboarding.schema import (
    BeFindableForm,
    FirstOpeningForm,
    MinimalProfileForm,
    ReferralFromWizardForm,
    StartNetworkForm,
    VerifyForm,
)
from src.domain.logic.onboarding.services import (
    complete_minimal_profile,
    create_first_opening,
    create_referral_from_wizard,
    update_clinician_for_findability,
    verify_and_create_clinician,
)
from src.domain.logic.onboarding.state_machine import next_step, onboarding_clinician
from src.domain.models import OpeningDetail, User
from src.domain.models.enums import (
    AVAILABILITY_STATES,
    AVAILABILITY_STATES_LABELS,
    LICENSE_TYPES,
    LICENSE_TYPES_LABELS,
    OPENING_TYPES,
    OPENING_TYPES_LABELS,
)
from src.framework import BaseRouter
from src.framework.http.form_error_handler import FormError, form_error_handler
from src.framework.http.responses import APIResponse

welcome_api_router = APIRouter(tags=["Welcome Wizard"])
router = BaseRouter(router=welcome_api_router, default_tags=["Welcome Wizard"])

# Hardcoded specialty vocabulary — same list rendered on all three
# specialty-picker surfaces (start-network + minimal-profile for C, and
# the first-opening form for B).
_SPECIALTIES = [
    "Trauma/PTSD",
    "EMDR",
    "Anxiety",
    "OCD/ERP",
    "Depression",
    "Grief",
    "Couples",
    "Adolescents",
    "ADHD",
    "Perinatal",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MalformedVerifyBody(Exception):
    """Validation failed on POST /welcome/verify body."""

    def __init__(self, errors: list[dict]):
        self.errors = errors


class _MalformedFirstOpeningBody(Exception):
    """Validation failed on POST /welcome/first-opening body."""

    def __init__(self, errors: list[dict]):
        self.errors = errors


class _MalformedBeFindableBody(Exception):
    """Validation failed on POST /welcome/be-findable body."""

    def __init__(self, errors: list[dict]):
        self.errors = errors


class _MalformedStartNetworkBody(Exception):
    """Validation failed on POST /welcome/start-network body."""

    def __init__(self, errors: list[dict]):
        self.errors = errors


class _MalformedMinimalProfileBody(Exception):
    """Validation failed on POST /welcome/minimal-profile body."""

    def __init__(self, errors: list[dict]):
        self.errors = errors


def _render_verify_errors(exc: _MalformedVerifyBody) -> FormError:
    from src.framework.dispatch.mounts.create import build_form_errors_dict

    return FormError(
        field_errors=build_form_errors_dict(exc.errors),
        status_code=422,
    )


def _render_first_opening_errors(exc: _MalformedFirstOpeningBody) -> FormError:
    from src.framework.dispatch.mounts.create import build_form_errors_dict

    return FormError(
        field_errors=build_form_errors_dict(exc.errors),
        status_code=422,
    )


def _render_be_findable_errors(exc: _MalformedBeFindableBody) -> FormError:
    from src.framework.dispatch.mounts.create import build_form_errors_dict

    return FormError(
        field_errors=build_form_errors_dict(exc.errors),
        status_code=422,
    )


def _render_start_network_errors(exc: _MalformedStartNetworkBody) -> FormError:
    from src.framework.dispatch.mounts.create import build_form_errors_dict

    return FormError(
        field_errors=build_form_errors_dict(exc.errors),
        status_code=422,
    )


def _render_minimal_profile_errors(exc: _MalformedMinimalProfileBody) -> FormError:
    from src.framework.dispatch.mounts.create import build_form_errors_dict

    return FormError(
        field_errors=build_form_errors_dict(exc.errors),
        status_code=422,
    )


def _redirect(request: Request, url: str) -> Response:
    """Return HX-Redirect for HTMX requests; plain 302 otherwise."""
    if request.headers.get("HX-Request") == "true":
        response = Response(status_code=204)
        response.headers["HX-Redirect"] = url
        return response
    return RedirectResponse(url=url, status_code=302)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


@router.get("/welcome", name="welcome:index")
async def get_welcome(
    request: Request,
    requesting_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Wizard dispatcher — calls next_step and redirects.

    Authed users who land here are sent to their next wizard step.
    Anonymous users are sent to /auth/login (via the 401 handler in main.py).
    """
    next_url = await next_step(requesting_user, db=db)
    return _redirect(request, next_url)


# ---------------------------------------------------------------------------
# Verify step
# ---------------------------------------------------------------------------

_VERIFY_STEP_INFO = "Step 1 of 1"
_VERIFY_TEMPLATE = "welcome/verify.html"


_VERIFY_CONTEXT = {
    "step_info": _VERIFY_STEP_INFO,
    "license_types": LICENSE_TYPES,
    "license_types_labels": LICENSE_TYPES_LABELS,
}


@router.get("/welcome/verify", name="welcome:get_verify")
async def get_verify(
    request: Request,
    requesting_user: User = Depends(current_active_user),
):
    """Render the license-verification form."""
    return APIResponse.html_response(
        template_name=_VERIFY_TEMPLATE,
        context=_VERIFY_CONTEXT,
        request=request,
    )


@router.post("/welcome/verify", name="welcome:post_verify")
@form_error_handler(
    template=_VERIFY_TEMPLATE,
    handlers={_MalformedVerifyBody: _render_verify_errors},
    context_builder=lambda kwargs: _VERIFY_CONTEXT,
    # Browser-only form — no JSON contract to preserve, so re-render on
    # every client (not just HTMX).
    require_htmx=False,
)
async def post_verify(
    request: Request,
    body: dict = Body(...),
    requesting_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Validate VerifyForm, create Clinician + Licensure, run verification,
    redirect to next_step.

    Uses `body: dict = Body(...)` (raw JSON via hx-ext="json-enc") so the
    decorator can catch `_MalformedVerifyBody` before FastAPI's auto-validation
    would raise outside the decorator's reach.
    """
    try:
        form_data = VerifyForm.model_validate(body)
    except ValidationError as e:
        raise _MalformedVerifyBody(e.errors())

    await verify_and_create_clinician(form_data, requesting_user, db=db)

    # After the service commits, reload the user's providers relationship so
    # next_step sees the newly created Provider.
    await db.refresh(requesting_user)

    next_url = await next_step(requesting_user, db=db)
    return _redirect(request, next_url)


# ---------------------------------------------------------------------------
# First-opening step (B3)
# ---------------------------------------------------------------------------

_FIRST_OPENING_STEP_INFO = "Step 2 of 2"
_FIRST_OPENING_TEMPLATE = "welcome/first_opening.html"

_FIRST_OPENING_CONTEXT = {
    "step_info": _FIRST_OPENING_STEP_INFO,
    "opening_types": OPENING_TYPES,
    "opening_types_labels": OPENING_TYPES_LABELS,
    "availability_states": AVAILABILITY_STATES,
    "availability_states_labels": AVAILABILITY_STATES_LABELS,
}


@router.get("/welcome/first-opening", name="welcome:get_first_opening")
async def get_first_opening(
    request: Request,
    requesting_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Render the first-opening form (Step 2 of 2 for have_openings flow).

    Redirects to /welcome if preconditions aren't met (no verified clinician).
    """
    clinician = onboarding_clinician(requesting_user)
    if clinician is None:
        return _redirect(request, "/welcome")

    return APIResponse.html_response(
        template_name=_FIRST_OPENING_TEMPLATE,
        context=_FIRST_OPENING_CONTEXT,
        request=request,
    )


@router.post("/welcome/first-opening", name="welcome:post_first_opening")
@form_error_handler(
    template=_FIRST_OPENING_TEMPLATE,
    handlers={_MalformedFirstOpeningBody: _render_first_opening_errors},
    context_builder=lambda kwargs: _FIRST_OPENING_CONTEXT,
    require_htmx=False,
)
async def post_first_opening(
    request: Request,
    body: dict = Body(...),
    requesting_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Validate FirstOpeningForm, create the clinician_opening Post, redirect.

    Uses `body: dict = Body(...)` (raw JSON via hx-ext="json-enc") so the
    decorator catches `_MalformedFirstOpeningBody` before FastAPI's
    auto-validation fires outside the decorator's reach.

    The "skip note" button sends `{"skip_note": "1", ...}` — we strip
    `colleague_note` before validation when present.
    """
    if body.pop("skip_note", None):
        body.pop("colleague_note", None)

    try:
        form_data = FirstOpeningForm.model_validate(body)
    except Exception as e:
        from pydantic import ValidationError

        if isinstance(e, ValidationError):
            raise _MalformedFirstOpeningBody(e.errors())
        raise

    await create_first_opening(form_data, requesting_user, db=db)

    await db.refresh(requesting_user)

    next_url = await next_step(requesting_user, db=db)
    return _redirect(request, next_url)


# ---------------------------------------------------------------------------
# Done page (B4 / C4 — all flows that complete with an Opening)
# ---------------------------------------------------------------------------


@router.get("/welcome/done", name="welcome:done")
async def get_done(
    request: Request,
    requesting_user: User = Depends(current_active_user),
):
    """Final wizard page — rendered after the clinician's first Opening is live.

    Always 200 — no redirect on re-visit. The natural exit is the
    'Go to the board' CTA (→ /openings). See state_machine.py for
    why we don't use a session flag to redirect repeat visitors.
    """
    return APIResponse.html_response(
        template_name="welcome/done.html",
        context={"user": requesting_user},
        request=request,
    )


# ---------------------------------------------------------------------------
# Be-findable step (A3) — refer_now flow, Step 2 of 2
# ---------------------------------------------------------------------------

_BE_FINDABLE_STEP_INFO = "Step 2 of 2"
_BE_FINDABLE_TEMPLATE = "welcome/be_findable.html"


def _be_findable_context(clinician=None) -> dict:
    return {
        "step_info": _BE_FINDABLE_STEP_INFO,
        "specialties_choices": _SPECIALTIES,
        "clinician": clinician,
    }


@router.get("/welcome/be-findable", name="welcome:get_be_findable")
async def get_be_findable(
    request: Request,
    requesting_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Render the be-findable form (Step 2 of 2 for refer_now flow).

    Redirects to /welcome if preconditions aren't met (no verified clinician).
    """
    clinician = onboarding_clinician(requesting_user)
    if clinician is None:
        return _redirect(request, "/welcome")

    return APIResponse.html_response(
        template_name=_BE_FINDABLE_TEMPLATE,
        context=_be_findable_context(clinician=clinician),
        request=request,
    )


@router.post("/welcome/be-findable", name="welcome:post_be_findable")
@form_error_handler(
    template=_BE_FINDABLE_TEMPLATE,
    handlers={_MalformedBeFindableBody: _render_be_findable_errors},
    context_builder=lambda kwargs: _be_findable_context(),
    require_htmx=False,
)
async def post_be_findable(
    request: Request,
    body: dict = Body(...),
    requesting_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Validate BeFindableForm, update clinician specialties + modality, redirect.

    Uses `body: dict = Body(...)` (raw JSON via hx-ext="json-enc") so the
    decorator catches `_MalformedBeFindableBody` before FastAPI's
    auto-validation fires outside the decorator's reach.

    Empty submission (skip-for-now with neither box checked, no specialties)
    is accepted — `update_clinician_for_findability` treats it as a no-op
    write that still commits, leaving `has_reciprocity_profile` False and
    routing back here on next visit. The user exits by selecting at least
    one specialty AND one modality, or by navigating directly to /openings.
    """
    try:
        form_data = BeFindableForm.model_validate(body)
    except ValidationError as e:
        raise _MalformedBeFindableBody(e.errors())

    await update_clinician_for_findability(form_data, requesting_user, db=db)

    await db.refresh(requesting_user)

    next_url = await next_step(requesting_user, db=db)
    return _redirect(request, next_url)


# ---------------------------------------------------------------------------
# Coming-soon stub (placeholder for steps not yet built)
# ---------------------------------------------------------------------------


@router.get("/welcome/coming-soon", name="welcome:coming_soon")
async def get_coming_soon(
    request: Request,
    requesting_user: User = Depends(current_active_user),
):
    """Placeholder rendered for verified users while downstream steps are not
    yet built. This page disappears from the state machine once all stubs
    are filled in."""
    return APIResponse.html_response(
        template_name="welcome/coming_soon.html",
        context={},
        request=request,
    )


# ---------------------------------------------------------------------------
# Refer step — /welcome/refer/{opening_id}
# ---------------------------------------------------------------------------

_REFER_TEMPLATE = "welcome/refer.html"


class _MalformedReferBody(Exception):
    """Validation failed on POST /welcome/refer/{opening_id} body."""

    def __init__(self, errors: list[dict]):
        self.errors = errors


def _render_refer_errors(exc: _MalformedReferBody) -> FormError:
    from src.framework.dispatch.mounts.create import build_form_errors_dict

    return FormError(
        field_errors=build_form_errors_dict(exc.errors),
        status_code=422,
    )


def _refer_context(opening_detail: OpeningDetail | None, refer_url: str) -> dict:
    """Build template context for the refer step."""
    clinician = None
    if opening_detail is not None:
        provider = opening_detail.provider
        if provider is not None:
            clinician = provider.clinician
    return {
        "opening_detail": opening_detail,
        "clinician": clinician,
        "refer_url": refer_url,
    }


@router.get("/welcome/refer/{opening_id}", name="welcome:get_refer")
async def get_refer(
    request: Request,
    opening_id: uuid.UUID,
    requesting_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Render the send-referral form for a specific clinician opening."""
    opening_detail = await db.get(OpeningDetail, opening_id)
    if opening_detail is None:
        raise HTTPException(status_code=404, detail="Opening not found.")
    refer_url = f"/welcome/refer/{opening_id}"
    return APIResponse.html_response(
        template_name=_REFER_TEMPLATE,
        context=_refer_context(opening_detail, refer_url),
        request=request,
    )


@router.post("/welcome/refer/{opening_id}", name="welcome:post_refer")
@form_error_handler(
    template=_REFER_TEMPLATE,
    handlers={_MalformedReferBody: _render_refer_errors},
    context_builder=lambda kwargs: _refer_context(
        getattr(kwargs["request"].state, "_opening_detail", None),
        getattr(kwargs["request"].state, "_refer_url", ""),
    ),
    require_htmx=False,
)
async def post_refer(
    request: Request,
    opening_id: uuid.UUID,
    body: dict = Body(...),
    requesting_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Validate ReferralFromWizardForm, create Referral post, redirect to /openings.

    Uses `body: dict = Body(...)` (raw JSON via hx-ext="json-enc") so the
    decorator can catch `_MalformedReferBody` before FastAPI's auto-validation
    would raise outside the decorator's reach. The opening context is stashed
    on `request.state` so `context_builder` can re-render the form with
    opening info on validation errors.
    """
    opening_detail = await db.get(OpeningDetail, opening_id)
    if opening_detail is None:
        raise HTTPException(status_code=404, detail="Opening not found.")

    # Stash on request.state so context_builder can access it for re-render.
    request.state._opening_detail = opening_detail
    request.state._refer_url = f"/welcome/refer/{opening_id}"

    # Always use the URL path param as the authoritative opening_id —
    # inject it into the body so Pydantic validates it round-trips cleanly.
    body["target_opening_id"] = str(opening_id)

    try:
        form_data = ReferralFromWizardForm.model_validate(body)
    except ValidationError as e:
        raise _MalformedReferBody(e.errors())

    await create_referral_from_wizard(form_data, requesting_user, db=db)
    return _redirect(request, "/openings")


# ---------------------------------------------------------------------------
# Start-network step (C1b — building_network flow only)
# ---------------------------------------------------------------------------

_START_NETWORK_TEMPLATE = "welcome/start_network.html"


@router.get("/welcome/start-network", name="welcome:get_start_network")
async def get_start_network(
    request: Request,
    requesting_user: User = Depends(current_active_user),
):
    """Render the specialty-picker card for the building_network flow."""
    session_specialties = request.session.get("start_network_specialties", [])
    return APIResponse.html_response(
        template_name=_START_NETWORK_TEMPLATE,
        context={
            "specialties": _SPECIALTIES,
            "selected_specialties": session_specialties,
            "step_info": "Step 1 of 3",
        },
        request=request,
    )


@router.post("/welcome/start-network", name="welcome:post_start_network")
@form_error_handler(
    template=_START_NETWORK_TEMPLATE,
    handlers={_MalformedStartNetworkBody: _render_start_network_errors},
    context_builder=lambda kwargs: {
        "specialties": _SPECIALTIES,
        "selected_specialties": [],
        "step_info": "Step 1 of 3",
    },
    require_htmx=False,
)
async def post_start_network(
    request: Request,
    body: dict = Body(...),
    requesting_user: User = Depends(current_active_user),
):
    """Save specialty selections to the session, redirect to /welcome/verify."""
    try:
        form_data = StartNetworkForm.model_validate(body)
    except ValidationError as e:
        raise _MalformedStartNetworkBody(e.errors())

    request.session["start_network_specialties"] = form_data.specialties
    return _redirect(request, "/welcome/verify")


# ---------------------------------------------------------------------------
# Minimal-profile step (C3 — building_network + invited flows)
# ---------------------------------------------------------------------------

_MINIMAL_PROFILE_TEMPLATE = "welcome/minimal_profile.html"


def _minimal_profile_context(clinician, user, session_specialties):
    return {
        "specialties": _SPECIALTIES,
        "selected_specialties": session_specialties,
        "clinician": clinician,
        "availability_states": AVAILABILITY_STATES,
        "opening_types": OPENING_TYPES,
        "user": user,
    }


@router.get("/welcome/minimal-profile", name="welcome:get_minimal_profile")
async def get_minimal_profile(
    request: Request,
    requesting_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Render the minimal-profile form (specialties, availability, opening type)."""
    clinician = onboarding_clinician(requesting_user)
    if clinician is None:
        return _redirect(request, "/welcome")
    session_specialties = request.session.get("start_network_specialties", [])
    return APIResponse.html_response(
        template_name=_MINIMAL_PROFILE_TEMPLATE,
        context=_minimal_profile_context(
            clinician, requesting_user, session_specialties
        ),
        request=request,
    )


@router.post("/welcome/minimal-profile", name="welcome:post_minimal_profile")
@form_error_handler(
    template=_MINIMAL_PROFILE_TEMPLATE,
    handlers={_MalformedMinimalProfileBody: _render_minimal_profile_errors},
    context_builder=lambda kwargs: _minimal_profile_context(
        onboarding_clinician(kwargs.get("requesting_user")),
        kwargs.get("requesting_user"),
        [],
    ),
    require_htmx=False,
)
async def post_minimal_profile(
    request: Request,
    body: dict = Body(...),
    requesting_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Validate MinimalProfileForm, create first Opening, redirect via next_step.

    Skip path: when body contains `skip=1`, bypass validation and create a
    minimal Opening using the first valid enum values as defaults. Specialties
    from the session are still applied on skip.
    """
    session_specialties = request.session.pop("start_network_specialties", [])

    if body.get("skip"):
        # Ghost-submit: create a minimal Opening with default values so the
        # clinician is on the board. Specialties from start-network are applied.
        skip_form = MinimalProfileForm(
            specialties=session_specialties,
            availability_state=AVAILABILITY_STATES[0],
            opening_type=OPENING_TYPES[0],
        )
        await complete_minimal_profile(
            skip_form, requesting_user, db=db, session_specialties=session_specialties
        )
    else:
        try:
            form_data = MinimalProfileForm.model_validate(body)
        except ValidationError as e:
            # Restore session key so the user can re-submit without losing selections
            request.session["start_network_specialties"] = session_specialties
            raise _MalformedMinimalProfileBody(e.errors())

        await complete_minimal_profile(
            form_data, requesting_user, db=db, session_specialties=session_specialties
        )

    await db.refresh(requesting_user)
    next_url = await next_step(requesting_user, db=db)
    return _redirect(request, next_url)
