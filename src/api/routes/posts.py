import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse

from src.api.common import APIResponse, BaseRouter
from src.auth_config import current_active_user
from src.logic.post_processing import (
    handle_create_post,
    handle_delete_post,
    handle_get_post_detail,
    handle_get_post_edit_form,
    handle_get_post_form,
    handle_list_posts,
    handle_update_post,
)
from src.models import User
from src.repositories.audit_repository import AuditRepository
from src.repositories.dependencies import get_audit_repository, get_post_repository
from src.repositories.post_repository import PostRepository
from src.schemas.post import PostCreate, PostUpdate

posts_api_router = APIRouter(prefix="/posts")
router = BaseRouter(router=posts_api_router, default_tags=["posts"])
logger = logging.getLogger(__name__)


# Per-kind create-form templates. The list is closed: a `kind` query
# value not in here yields a 422 from FastAPI's Literal validator,
# avoiding any chance of arbitrary template selection from the URL.
_CREATE_FORM_TEMPLATES: dict[str, str] = {
    "client_referral": "posts/new_client_referral.html",
    "provider_availability": "posts/new_provider_availability.html",
}
_EDIT_FORM_TEMPLATES: dict[str, str] = {
    "client_referral": "posts/edit_client_referral.html",
    "provider_availability": "posts/edit_provider_availability.html",
}


def _patch_response_body(post) -> dict:
    """Per-kind flat response body for `PATCH /posts/{id}`. The wire
    shape mirrors the POST/GET projection's flat fields so HTMX clients
    don't have to know about parent/detail."""
    if post.kind == "client_referral":
        return {
            "id": str(post.id),
            "kind": "client_referral",
            "description": post.client_referral_detail.description,
        }
    if post.kind == "provider_availability":
        return {
            "id": str(post.id),
            "kind": "provider_availability",
            "practice_name": post.provider_availability_detail.practice_name,
        }
    raise ValueError(f"unsupported post kind: {post.kind!r}")


@router.get("")
async def list_posts(
    request: Request,
    post_repo: PostRepository = Depends(get_post_repository),
    user: User = Depends(current_active_user),
):
    """Provides an HTML page listing all posts (newest first).
    Requires authentication.
    """
    context = await handle_list_posts(
        request=request,
        post_repo=post_repo,
        requesting_user=user,
    )
    return APIResponse.html_response(
        template_name="posts/list.html", context=context, request=request
    )


@router.get("/form")
async def get_post_form(
    request: Request,
    kind: Literal["client_referral", "provider_availability"] = Query(
        "client_referral"
    ),
    user: User = Depends(current_active_user),
):
    """Provides an HTML page with the create-post form for the given
    `kind` (default `'client_referral'`). Unsupported kinds 422 via
    FastAPI's Literal validator.

    Registered before `/{post_id}` so the literal `form` is not parsed
    as a UUID.
    """
    context = await handle_get_post_form(request=request, requesting_user=user)
    return APIResponse.html_response(
        template_name=_CREATE_FORM_TEMPLATES[kind], context=context, request=request
    )


@router.get("/{post_id}/form")
async def get_post_edit_form(
    post_id: UUID,
    request: Request,
    post_repo: PostRepository = Depends(get_post_repository),
    user: User = Depends(current_active_user),
):
    """Provides an HTML page with the edit-post form. Owner-only; admins may
    edit any post. The template is selected from the post's `kind`, so
    each kind's edit form lives in its own file. 404 if missing, 403 if
    not authorized.
    """
    context = await handle_get_post_edit_form(
        request=request,
        post_id=post_id,
        post_repo=post_repo,
        requesting_user=user,
    )
    post_kind = context["post"].kind
    return APIResponse.html_response(
        template_name=_EDIT_FORM_TEMPLATES[post_kind],
        context=context,
        request=request,
    )


@router.get("/{post_id}")
async def get_post(
    post_id: UUID,
    request: Request,
    post_repo: PostRepository = Depends(get_post_repository),
    user: User = Depends(current_active_user),
):
    """Provides an HTML detail page for a single post. The template
    branches on `post.kind` to render the right per-kind body."""
    context = await handle_get_post_detail(
        request=request,
        post_id=post_id,
        post_repo=post_repo,
        requesting_user=user,
    )
    return APIResponse.html_response(
        template_name="posts/detail.html", context=context, request=request
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_post(
    payload: PostCreate,
    post_repo: PostRepository = Depends(get_post_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    """Creates a post owned by the authenticated user.

    The body is a discriminated union on `kind`: clients must include
    a `kind` matching one of the registered variants. `owner_id` is
    server-set from the session; clients sending it (or any other
    unknown field) are rejected with 422 by the schema.
    """
    created = await handle_create_post(
        payload=payload,
        post_repo=post_repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    location = f"/posts/{created.id}"
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"id": str(created.id)},
        headers={"Location": location, "HX-Redirect": location},
    )


@router.patch("/{post_id}")
async def patch_post(
    post_id: UUID,
    payload: PostUpdate,
    post_repo: PostRepository = Depends(get_post_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    """Partially updates a post. Owner-only; admins may edit any post.

    Server-managed fields (`id`, `owner_id`, `created_at`, `updated_at`)
    are rejected by the schema's `extra="forbid"`. The body must include
    at least one mutable field for the post's kind. `kind` cannot be
    changed via PATCH; mismatches are rejected with 400.
    """
    updated = await handle_update_post(
        post_id=post_id,
        payload=payload,
        post_repo=post_repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return JSONResponse(
        content=_patch_response_body(updated),
        headers={"HX-Refresh": "true"},
    )


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    post_id: UUID,
    post_repo: PostRepository = Depends(get_post_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    """Hard-deletes a post. Owner-only; admins may delete any post.
    404 if missing, 403 if not authorized.
    """
    await handle_delete_post(
        post_id=post_id,
        post_repo=post_repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"HX-Redirect": "/posts"},
    )
