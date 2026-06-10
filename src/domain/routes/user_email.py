"""Bespoke routes for the `/users/me/email` field-cluster subresource.

    GET /users/me/email/form    email management page (self-only)

Houses verification status and the resend-verification action. Email
change (PUT /users/me/email) belongs here when implemented.

Doubles as the post-registration / post-resend CTA: when the viewer
is unverified, the page renders an "open your inbox" affordance —
smart link to the recognized webmail provider when we have one, plain
fallback otherwise. `?sent=1` (set by the resend redirect) swaps the
lede to a "just sent another email" confirmation.

Follows the bespoke-route pattern documented in
`src/domain/routes/README.md § Bespoke routes`.
"""

from fastapi import APIRouter, Depends, Request

from src.auth_config import current_active_user
from src.domain.logic.auth.email_providers import email_provider_search_url
from src.domain.models import User
from src.domain.specs.user import USER_ENTITY
from src.framework.config import settings
from src.framework.http.responses import APIResponse
from src.framework.rendering.route_urls import url_for_spec

user_email_router = APIRouter(prefix="/users/me/email", tags=["users"])


@user_email_router.get("/form", name="user_email:form")
async def get_email_form(
    request: Request,
    current_user: User = Depends(current_active_user),
):
    label, url = email_provider_search_url(current_user.email, settings.EMAIL_FROM)
    return APIResponse.html_response(
        template_name="users/email_form.html",
        context={
            "target_user": current_user,
            # `entity_name` powers the breadcrumb's `breadcrumb_entity_item`
            # call in `views/form_edit.html` — bespoke routes that extend a
            # view-type chrome must inject the same key the generic mounts do.
            "entity_name": USER_ENTITY.name,
            "resource_url": url_for_spec(USER_ENTITY),
            "resource_detail_url": url_for_spec(USER_ENTITY, id=current_user.id),
            "edit_heading": "Email",
            # Inbox-CTA payload — used by the template only when the
            # viewer is unverified; harmless to compute either way.
            "provider_label": label,
            "provider_url": url,
            "from_address": settings.EMAIL_FROM,
            "just_sent": request.query_params.get("sent") == "1",
        },
        request=request,
        current_user=current_user,
    )
