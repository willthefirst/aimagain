from fastapi import APIRouter, Request
from fastapi.responses import Response

from src.framework import APIResponse, BaseRouter

# Standardized router initialization
auth_pages_api_router = APIRouter(prefix="/auth")
router = BaseRouter(router=auth_pages_api_router, default_tags=["Auth Pages"])


@router.get("/register", name="auth_pages:register")
async def get_register_page(request: Request):
    return APIResponse.html_response(
        template_name="auth/register.html", context={}, request=request
    )


@router.get("/login", name="auth_pages:login")
async def get_login_page(request: Request):
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
    return APIResponse.html_response(
        template_name="auth/forgot_password.html", context={}, request=request
    )


@router.get("/reset-password/{token}", name="auth_pages:reset_password")
async def get_reset_password_page(request: Request, token: str):
    return APIResponse.html_response(
        template_name="auth/reset_password.html",
        context={"token": token},
        request=request,
    )


@router.post("/sign-out", name="auth_pages:sign_out")
async def post_sign_out(request: Request):
    """Clear the session cookie and redirect to login (#702).

    Clears `fastapiusersauth` (the CookieTransport cookie name) and
    returns HX-Redirect so HTMX does a full-page navigation to the
    login page, reflecting the anonymous state immediately.
    """
    response = Response(status_code=200)
    response.delete_cookie("fastapiusersauth")
    response.headers["HX-Redirect"] = "/auth/login"
    return response
