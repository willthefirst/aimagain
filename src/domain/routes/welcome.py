"""Bespoke router for the /welcome onboarding wizard.

Pattern: every step is a `GET /welcome/<step>` page + `POST /welcome/<step>`
shim. The shim validates → calls a service function → redirects via
`next_step()`. On validation error the form fragment is re-rendered with
errors inline.

This router is intentionally thin — all business logic lives in
`src/domain/logic/onboarding/`.

Modeled on `src/domain/routes/auth_pages.py`.
"""

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth_config import current_active_user
from src.db import get_db_session
from src.domain.logic.onboarding.schema import VerifyForm
from src.domain.logic.onboarding.services import verify_and_create_clinician
from src.domain.logic.onboarding.state_machine import next_step
from src.domain.models import User
from src.domain.models.enums import LICENSE_TYPES, LICENSE_TYPES_LABELS
from src.framework import BaseRouter
from src.framework.http.form_error_handler import FormError, form_error_handler
from src.framework.http.responses import APIResponse

welcome_api_router = APIRouter(tags=["Welcome Wizard"])
router = BaseRouter(router=welcome_api_router, default_tags=["Welcome Wizard"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MalformedVerifyBody(Exception):
    """Validation failed on POST /welcome/verify body."""

    def __init__(self, errors: list[dict]):
        self.errors = errors


def _render_verify_errors(exc: _MalformedVerifyBody) -> FormError:
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
# Coming-soon stub (placeholder for T4/T5/T7 steps)
# ---------------------------------------------------------------------------


@router.get("/welcome/coming-soon", name="welcome:coming_soon")
async def get_coming_soon(
    request: Request,
    requesting_user: User = Depends(current_active_user),
):
    """Placeholder rendered for verified users while downstream steps are not
    yet built. T4/T5/T7 will replace the real pages; this page disappears
    from the state machine once all stubs are filled in."""
    return APIResponse.html_response(
        template_name="welcome/coming_soon.html",
        context={},
        request=request,
    )
