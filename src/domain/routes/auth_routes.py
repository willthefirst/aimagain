import logging

from fastapi import APIRouter, Depends, Request, status
from fastapi_users import exceptions as fa_users_exceptions
from fastapi_users import models
from fastapi_users.manager import BaseUserManager
from fastapi_users.router.common import ErrorCode, ErrorModel

from src.auth_config import auth_backend, get_strategy, get_user_manager
from src.domain.logic.auth.handlers import handle_registration
from src.domain.logic.users.schema import UserCreate, UserRead
from src.framework import BaseRouter
from src.framework.audit.repository import AuditRepository
from src.framework.http.form_error_handler import FormError, form_error_handler
from src.framework.http.form_rerender import form_rerender
from src.framework.persistence.dependencies import get_audit_repository

auth_api_router = APIRouter()
router = BaseRouter(router=auth_api_router, default_tags=["auth"])

logger = logging.getLogger(__name__)

register_responses = {
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorModel,
        "content": {
            "application/json": {
                "examples": {
                    ErrorCode.REGISTER_USER_ALREADY_EXISTS: {
                        "summary": "A user with this email already exists.",
                        "value": {"detail": ErrorCode.REGISTER_USER_ALREADY_EXISTS},
                    },
                    ErrorCode.REGISTER_INVALID_PASSWORD: {
                        "summary": "Password validation failed.",
                        "value": {
                            "detail": {
                                "code": ErrorCode.REGISTER_INVALID_PASSWORD,
                                "reason": "Password should be ...",
                            }
                        },
                    },
                }
            }
        },
    },
    status.HTTP_500_INTERNAL_SERVER_ERROR: {
        "model": ErrorModel,
        "content": {
            "application/json": {
                "examples": {
                    "server_error": {
                        "summary": "An unexpected server error occurred.",
                        "value": {
                            "detail": "An unexpected error occurred during registration."
                        },
                    }
                }
            }
        },
    },
}


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    tags=["auth"],
    name="auth:register",
    responses=register_responses,
)
@form_error_handler(
    # `form_error_handler` is applied *between* `BaseRouter`'s
    # `handle_route_errors` wrap and the function body. On a registered
    # exception + `HX-Request: true` it short-circuits with a 200 +
    # form fragment via `form_rerender`. Anything else (non-HTMX call,
    # unregistered exception) re-raises so `handle_route_errors`
    # translates it into the documented JSON 4xx — preserving the
    # contract pinned by `test_register_duplicate_email`.
    #
    # Email is the only field we prefill — password is intentionally
    # never echoed back into HTML.
    template="auth/_register_form.html",
    prefill_fields=("email",),
    handlers={
        fa_users_exceptions.UserAlreadyExists: lambda e: FormError(
            field_errors={"email": "An account with this email already exists."}
        ),
        fa_users_exceptions.InvalidPasswordException: lambda e: FormError(
            field_errors={"password": e.reason}
        ),
    },
)
async def register_request_handler(
    request_data: UserCreate,
    request: Request,
    user_manager: BaseUserManager[models.UP, models.ID] = Depends(get_user_manager),
    audit_repo: AuditRepository = Depends(get_audit_repository),
):
    logger.debug(f"Handling registration for email: {request_data.email}")
    is_htmx = request.headers.get("HX-Request") == "true"
    try:
        created_user = await handle_registration(
            request_data=request_data,
            request=request,
            user_manager=user_manager,
            audit_repo=audit_repo,
        )
    except fa_users_exceptions.UserAlreadyExists:
        # HTMX submit: re-render the form fragment in place with a
        # per-field error pointing at `email` instead of letting the
        # `handle_route_errors` decorator translate this into a JSON
        # 400 that HTMX has nowhere to land. Password is *not* echoed
        # back into form HTML — only the email is prefilled via
        # `form_values["email"]` (see `_register_form.html`).
        # Non-HTMX clients preserve the existing JSON 400 contract
        # (programmatic clients, contract tests) — fall through to
        # re-raise so the decorator does its translation.
        if is_htmx:
            return form_rerender(
                request=request,
                template_name="auth/_register_form.html",
                field_errors={
                    "email": "An account with this email already exists.",
                },
                values={"email": request_data.email},
            )
        raise
    except fa_users_exceptions.InvalidPasswordException as e:
        # Same rerender pattern for the password-policy failure case.
        # `e.reason` carries the policy-specific message the password
        # validator raised (length, char-class, etc.) — surface it
        # directly so the user knows what to fix.
        if is_htmx:
            return form_rerender(
                request=request,
                template_name="auth/_register_form.html",
                field_errors={"password": e.reason},
                values={"email": request_data.email},
            )
        raise

    if is_htmx:
        # HTMX submit: auto-login and redirect instead of returning raw JSON.
        # Mirrors the pattern in src/domain/routes/dev_auth.py.
        login_response = await auth_backend.login(get_strategy(), created_user)
        login_response.status_code = 200
        login_response.headers["HX-Redirect"] = "/users/me"
        return login_response

    return created_user
