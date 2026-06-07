"""Bespoke routes for the `/users/me/email` field-cluster subresource.

    GET /users/me/email/form    email management page (self-only)

Houses verification status and the resend-verification action. Email
change (PUT /users/me/email) belongs here when implemented.

Follows the bespoke-route pattern documented in
`src/domain/routes/README.md § Bespoke routes`.
"""

from fastapi import APIRouter, Depends, Request

from src.auth_config import current_active_user
from src.domain.models import User
from src.domain.specs.user import USER_ENTITY
from src.framework.http.responses import APIResponse
from src.framework.rendering.route_urls import url_for_spec

user_email_router = APIRouter(prefix="/users/me/email", tags=["users"])


@user_email_router.get("/form", name="user_email:form")
async def get_email_form(
    request: Request,
    current_user: User = Depends(current_active_user),
):
    return APIResponse.html_response(
        template_name="users/email_form.html",
        context={
            "target_user": current_user,
            "resource_url": url_for_spec(USER_ENTITY),
            "resource_detail_url": url_for_spec(USER_ENTITY, id=current_user.id),
            "edit_heading": "Email",
        },
        request=request,
        current_user=current_user,
    )
