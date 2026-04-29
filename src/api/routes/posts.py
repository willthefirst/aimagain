import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from src.api.common import APIResponse, BaseRouter
from src.auth_config import current_active_user
from src.logic.post_processing import (
    handle_create_post,
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
    user: User = Depends(current_active_user),
):
    """Provides an HTML page with the create-post form.

    Registered before `/{post_id}` so the literal `form` is not parsed as a UUID.
    """
    context = await handle_get_post_form(request=request, requesting_user=user)
    return APIResponse.html_response(
        template_name="posts/new.html", context=context, request=request
    )


@router.get("/{post_id}/form")
async def get_post_edit_form(
    post_id: UUID,
    request: Request,
    post_repo: PostRepository = Depends(get_post_repository),
    user: User = Depends(current_active_user),
):
    """Provides an HTML page with the edit-post form. Owner-only; admins may
    edit any post. 404 if missing, 403 if not authorized.
    """
    context = await handle_get_post_edit_form(
        request=request,
        post_id=post_id,
        post_repo=post_repo,
        requesting_user=user,
    )
    return APIResponse.html_response(
        template_name="posts/edit.html", context=context, request=request
    )


@router.get("/{post_id}")
async def get_post(
    post_id: UUID,
    request: Request,
    post_repo: PostRepository = Depends(get_post_repository),
    user: User = Depends(current_active_user),
):
    """Provides an HTML detail page for a single post."""
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

    `owner_id` is server-set from the session; clients sending it (or any
    other unknown field) are rejected with 422 by the schema.
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

    Server-managed fields (`id`, `owner_id`, `created_at`, `updated_at`) are
    rejected by the schema's `extra="forbid"`. The body must include at least
    one of `title`/`body`.
    """
    updated = await handle_update_post(
        post_id=post_id,
        payload=payload,
        post_repo=post_repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return JSONResponse(
        content={"id": str(updated.id), "title": updated.title, "body": updated.body},
        headers={"HX-Refresh": "true"},
    )
