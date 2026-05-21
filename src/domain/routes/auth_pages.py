from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from fastapi_users import exceptions as fa_users_exceptions
from fastapi_users import models
from fastapi_users.manager import BaseUserManager

from src.auth_config import current_active_user, get_user_manager
from src.domain.models import User
from src.framework import APIResponse, BaseRouter

# Standardized router initialization
auth_pages_api_router = APIRouter(prefix="/auth")
router = BaseRouter(router=auth_pages_api_router, default_tags=["Auth Pages"])


@router.get("/register", name="auth_pages:register")
async def get_register_page(request: Request):
    """Serves the HTML registration page.

    This endpoint is automatically logged and error-handled by the BaseRouter decorators.

    Returns:
        TemplateResponse: The rendered HTML page.
    """
    return APIResponse.html_response(
        template_name="auth/register.html", context={}, request=request
    )


@router.get("/login", name="auth_pages:login")
async def get_login_page(request: Request):
    """Serves the HTML login page.

    This endpoint is automatically logged and error-handled by the BaseRouter decorators.

    Returns:
        TemplateResponse: The rendered HTML page.
    """
    next_url = request.query_params.get("next", "")
    # Show a contextual message when arriving from the registration flow
    just_registered = request.query_params.get("registered") == "1"
    return APIResponse.html_response(
        template_name="auth/login.html",
        context={"next_url": next_url, "just_registered": just_registered},
        request=request,
    )


@router.get("/forgot-password", name="auth_pages:forgot_password")
async def get_forgot_password_page(request: Request):
    """Serves the HTML forgot password page.

    This endpoint is automatically logged and error-handled by the BaseRouter decorators.

    Returns:
        TemplateResponse: The rendered HTML page.
    """
    return APIResponse.html_response(
        template_name="auth/forgot_password.html", context={}, request=request
    )


@router.get("/reset-password/{token}", name="auth_pages:reset_password")
async def get_reset_password_page(request: Request, token: str):
    """Serves the HTML reset password page, including the token.

    Args:
        request: The FastAPI request object.
        token: The password reset token from the URL path.

    This endpoint is automatically logged and error-handled by the BaseRouter decorators.

    Returns:
        TemplateResponse: The rendered HTML page with the token in context.
    """
    return APIResponse.html_response(
        template_name="auth/reset_password.html",
        context={"token": token},
        request=request,
    )


@router.get("/verify", name="auth_pages:verify")
async def get_verify_page(
    request: Request,
    user_manager: BaseUserManager[models.UP, models.ID] = Depends(get_user_manager),
):
    """Consume the verify token from the email link.

    The email contains `GET /auth/verify?token=...`. Calling
    `user_manager.verify(token)` server-side keeps the user out of any
    HTMX/JS ceremony — the click comes from an email client, which may
    not run JS at all. Renders one of three states:

      - `status="success"`: token consumed, account verified.
      - `status="already_verified"`: token valid but `is_verified`
        already True. Treated as success in the UI; explicit branch so
        a future "the link doesn't seem to work" copy can differentiate.
      - `status="error"`: token missing / expired / malformed. The page
        offers a "resend" link back to the nag banner (`/users/me`).
    """
    token = request.query_params.get("token", "")
    if not token:
        status = "error"
    else:
        try:
            await user_manager.verify(token, request)
            status = "success"
        except fa_users_exceptions.UserAlreadyVerified:
            status = "already_verified"
        except (
            fa_users_exceptions.InvalidVerifyToken,
            fa_users_exceptions.UserNotExists,
        ):
            status = "error"
    return APIResponse.html_response(
        template_name="auth/verify.html",
        context={"status": status},
        request=request,
    )


@router.post("/resend-verify", name="auth_pages:resend_verify")
async def post_resend_verify(
    request: Request,
    current_user: User = Depends(current_active_user),
    user_manager: BaseUserManager[models.UP, models.ID] = Depends(get_user_manager),
):
    """Re-send the verify email for the currently-authed user.

    Sits in front of fastapi-users' `POST /auth/request-verify-token`
    so the nag banner doesn't need to expose the user's email in HTML
    (and doesn't need a JSON-encoding HTMX form). Reads the user from
    the session cookie; calls `request_verify` which triggers
    `on_after_request_verify` → `send_verification_email`.

    Returns the banner partial back to HTMX (`outerHTML` swap) so the
    nag is replaced with a confirmation message inline.
    """
    try:
        await user_manager.request_verify(current_user, request)
    except fa_users_exceptions.UserAlreadyVerified:
        # Edge case: user verified in another tab between page load
        # and the resend click. Render the same confirmation —
        # nothing to do from the user's POV.
        pass
    return APIResponse.html_response(
        template_name="_shared/_verify_banner_sent.html",
        context={},
        request=request,
    )


@router.post("/sign-out", name="auth_pages:sign_out")
async def post_sign_out(request: Request):
    """Clear the session cookie and redirect to the login page (#702).

    Deletes the `fastapiusersauth` cookie (CookieTransport default name)
    and sends `HX-Redirect` so HTMX does a full navigation — the chrome
    immediately reflects the anonymous state without a stale header.
    """
    response = Response(status_code=200)
    response.delete_cookie("fastapiusersauth")
    response.headers["HX-Redirect"] = "/auth/login"
    return response
