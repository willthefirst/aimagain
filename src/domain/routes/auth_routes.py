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
from src.framework.http.form_error_handler import form_error_handler
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
    # `catches=` pulls the rendering rules (status_code, field name,
    # default message) from `FormErrorRegistry`. The two fastapi-users
    # exceptions are registered at framework boot in
    # `src/framework/http/form_error_registry.py`:
    #   - UserAlreadyExists      → 409 + email + "An account ..."
    #   - InvalidPasswordException → 422 + password + e.reason
    # If a future route needs different copy, it can override per
    # exception via `handlers={...}` on this decorator; the explicit
    # entry wins over the registry. Non-HTMX clients still get the
    # JSON 400 contract via `handle_route_errors`.
    # `prefill_fields` is omitted → auto-detect from the submitted
    # `UserCreate` body. The framework reads the Pydantic schema fields
    # (`email`, `password`, `username`) and prefills the non-sensitive
    # ones — `password` is dropped by `SENSITIVE_FIELD_NAMES`'s
    # substring rule. Adding a new visible field to `UserCreate` (e.g.
    # `display_name`) will prefill automatically; no per-route opt-in.
    template="auth/_register_form.html",
    catches=(
        fa_users_exceptions.UserAlreadyExists,
        fa_users_exceptions.InvalidPasswordException,
    ),
)
async def register_request_handler(
    request_data: UserCreate,
    request: Request,
    user_manager: BaseUserManager[models.UP, models.ID] = Depends(get_user_manager),
    audit_repo: AuditRepository = Depends(get_audit_repository),
):
    logger.debug(f"Handling registration for email: {request_data.email}")
    created_user = await handle_registration(
        request_data=request_data,
        request=request,
        user_manager=user_manager,
        audit_repo=audit_repo,
    )

    if request.headers.get("HX-Request") == "true":
        # HTMX submit: auto-login and redirect to the "check your email"
        # CTA so the user is nudged to open their inbox and click the
        # verify link. Mirrors the pattern in src/domain/routes/dev_auth.py.
        login_response = await auth_backend.login(get_strategy(), created_user)
        login_response.status_code = 200
        login_response.headers["HX-Redirect"] = "/auth/check-email"
        return login_response

    return created_user
