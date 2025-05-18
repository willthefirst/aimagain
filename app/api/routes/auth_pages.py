from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.core.templating import templates

router = APIRouter()


@router.get(
    "/auth/register",
    response_class=HTMLResponse,
    tags=["Auth Pages"],
    name="auth_pages:register",
)
async def get_register_page(request: Request):
    """Serves the HTML registration page."""
    return templates.TemplateResponse(
        name="auth/register.html", context={"request": request}
    )


@router.get(
    "/auth/login",
    response_class=HTMLResponse,
    tags=["Auth Pages"],
    name="auth_pages:login",
)
async def get_login_page(request: Request):
    """Serves the HTML login page."""
    return templates.TemplateResponse(
        name="auth/login.html", context={"request": request}
    )


@router.get(
    "/auth/forgot-password",
    response_class=HTMLResponse,
    tags=["Auth Pages"],
    name="auth_pages:forgot_password",
)
async def get_forgot_password_page(request: Request):
    """Serves the HTML forgot password page."""
    return templates.TemplateResponse(
        name="auth/forgot_password.html", context={"request": request}
    )


@router.get(
    "/auth/reset-password/{token}",
    response_class=HTMLResponse,
    tags=["Auth Pages"],
    name="auth_pages:reset_password",
)
async def get_reset_password_page(request: Request, token: str):
    """Serves the HTML reset password page, including the token."""
    return templates.TemplateResponse(
        name="auth/reset_password.html", context={"request": request, "token": token}
    )
