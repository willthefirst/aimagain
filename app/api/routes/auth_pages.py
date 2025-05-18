from fastapi import APIRouter, Request

from app.api.common import APIResponse, BaseRouter

# Standardized router initialization
auth_pages_api_router = APIRouter(prefix="/auth")
router = BaseRouter(router=auth_pages_api_router, default_tags=["Auth Pages"])


@router.get("/register", name="auth_pages:register")
async def get_register_page(request: Request):
    """Serves the HTML registration page."""
    return APIResponse.html_response(
        template_name="auth/register.html", context={}, request=request
    )


@router.get("/login", name="auth_pages:login")
async def get_login_page(request: Request):
    """Serves the HTML login page."""
    return APIResponse.html_response(
        template_name="auth/login.html", context={}, request=request
    )


@router.get("/forgot-password", name="auth_pages:forgot_password")
async def get_forgot_password_page(request: Request):
    """Serves the HTML forgot password page."""
    return APIResponse.html_response(
        template_name="auth/forgot_password.html", context={}, request=request
    )


@router.get("/reset-password/{token}", name="auth_pages:reset_password")
async def get_reset_password_page(request: Request, token: str):
    """Serves the HTML reset password page, including the token."""
    return APIResponse.html_response(
        template_name="auth/reset_password.html",
        context={"token": token},
        request=request,
    )
