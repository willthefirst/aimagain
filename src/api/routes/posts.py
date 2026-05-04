import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
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


def _edit_template_for(kind: str) -> str:
    """Per-kind edit template lookup. Add an entry when a kind grows
    editable fields and a corresponding template under
    `src/templates/posts/edit_<kind>.html`."""
    return {
        "client_referral": "posts/edit_client_referral.html",
    }[kind]


@router.get("")
async def list_posts(
    request: Request,
    post_repo: PostRepository = Depends(get_post_repository),
    user: User = Depends(current_active_user),
):
    """Provides an HTML page listing all posts (newest first, every kind).
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
    """Provides an HTML page with the create-post form (kind selector +
    per-kind field clusters that show/hide based on the selected radio).

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
    edit any post. 404 if missing, 403 if not authorized, 404 if the post's
    kind has no editable fields yet.
    """
    context = await handle_get_post_edit_form(
        request=request,
        post_id=post_id,
        post_repo=post_repo,
        requesting_user=user,
    )
    return APIResponse.html_response(
        template_name=_edit_template_for(context["post"].kind),
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
    """Provides an HTML detail page for a single post (kind-aware)."""
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

    Body is the kind-discriminated `PostCreate` union; the `kind` field
    selects the subclass and is server-trusted only as a discriminator (the
    union rejects unknown kinds with 422). `owner_id` is server-set from the
    session; clients sending it (or any other unknown field) are rejected
    with 422 by the per-kind schema's `extra="forbid"`.
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

    The body's `kind` discriminator selects the per-kind update schema and
    must match the persisted post's kind (the handler 400s on mismatch).
    The schema enforces `extra="forbid"` and at-least-one-editable-field.
    """
    updated = await handle_update_post(
        post_id=post_id,
        payload=payload,
        post_repo=post_repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return JSONResponse(
        content={"id": str(updated.id)},
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
