import logging
from uuid import UUID

from fastapi import Request

from src.api.common.exceptions import BadRequestError, NotFoundError
from src.api.common.specs.post import POST_ENTITY
from src.logic._authz import assert_owner_or_admin, is_admin, is_owner
from src.logic.audit import mutate
from src.models import POST_KINDS, Post, User
from src.repositories.audit_repository import AuditRepository
from src.repositories.posts.post_repository import PostRepository
from src.schemas.posts.post import (
    ClientReferralCreate,
    ClientReferralUpdate,
    ProviderAvailabilityCreate,
    ProviderAvailabilityUpdate,
)

logger = logging.getLogger(__name__)

PostCreatePayload = ClientReferralCreate | ProviderAvailabilityCreate
PostUpdatePayload = ClientReferralUpdate | ProviderAvailabilityUpdate


# Audit binding lives on the spec (single declaration). Re-exported as
# `POST` so handler bodies can keep their `resource=POST` shape.
POST = POST_ENTITY.audit


async def handle_list_posts(
    request: Request,
    repo: PostRepository,
    requesting_user: User,
):
    """Loads all posts (newest first) and returns the template context.

    Includes the registered post kinds in the context so the list page
    can render its per-kind "New X" links from a single source of truth.
    """
    posts = await repo.list_posts()
    return {
        "request": request,
        "posts": posts,
        "current_user": requesting_user,
        "post_kinds": list(POST_KINDS.values()),
    }


async def handle_get_post_detail(
    request: Request,
    post_id: UUID,
    repo: PostRepository,
    requesting_user: User,
):
    """Loads a single post for the detail page; 404s if missing.

    Computes `can_edit` (owner-or-admin) so the owner-actions partial
    can render based on a single named flag instead of re-deriving the
    rule against `current_user`.
    """
    post = await repo.get_post_by_id(post_id)
    if post is None:
        raise NotFoundError(detail="Post not found")

    return {
        "request": request,
        "post": post,
        "current_user": requesting_user,
        "can_edit": is_owner(post, requesting_user) or is_admin(requesting_user),
    }


async def handle_get_post_form(
    request: Request,
    requesting_user: User,
    repo: PostRepository | None = None,
    kind: str = "",
):
    """Builds the template context for the create-post form.

    `kind` picks the per-kind create template; the handler returns
    `template_name` in the context so `mount_form` renders the
    kind-specific template. Empty `kind` defaults to the first
    registered kind, matching the previous bespoke route's
    `Query(POST_KIND_NAMES[0])` default. `repo` is accepted for uniformity
    with the mount_form contract but unused here.
    """
    del repo  # explicitly unused
    chosen_kind = kind or next(iter(POST_KINDS))
    return {
        "request": request,
        "current_user": requesting_user,
        "template_name": POST_KINDS[chosen_kind].create_template,
    }


async def handle_get_post_edit_form(
    request: Request,
    post_id: UUID,
    repo: PostRepository,
    requesting_user: User,
):
    """Loads a post for the edit-form page. 404 if missing, 403 if the
    requester is neither owner nor admin (mirrors `handle_update_post`).

    Returns ``template_name`` in the context so `mount_form` renders the
    kind-specific edit template (each post kind has its own edit page).
    The mount pops ``template_name`` before rendering so it doesn't leak
    into the Jinja context.
    """
    post = await repo.get_post_by_id(post_id)
    if post is None:
        raise NotFoundError(detail="Post not found")

    assert_owner_or_admin(post, requesting_user, action="edit this post")

    return {
        "request": request,
        "post": post,
        "current_user": requesting_user,
        "template_name": POST_KINDS[post.kind].edit_template,
    }


async def handle_update_post(
    post_id: UUID,
    payload: PostUpdatePayload,
    repo: PostRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> Post:
    """Patches a post owned by the requesting user (or by anyone, if the
    requester is a superuser). Writes an audit row capturing before/after
    snapshots in the same transaction; commits on success.

    The payload's `kind` must match the persisted post's `kind` — `kind`
    is part of the resource identity once created and cannot be migrated
    via PATCH. 404 if missing, 403 if not authorized, 400 on kind
    mismatch. Per-kind field set comes from `POST_KINDS`.
    """
    post = await repo.get_post_by_id(post_id)
    if post is None:
        raise NotFoundError(detail="Post not found")

    assert_owner_or_admin(post, requesting_user, action="edit this post")

    if payload.kind != post.kind:
        raise BadRequestError(
            detail=(
                f"payload kind {payload.kind!r} does not match post kind "
                f"{post.kind!r}; kind cannot be changed via PATCH"
            )
        )

    spec = POST_KINDS[payload.kind]
    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=post,
        resource=POST,
        verb="update",
    ):
        await repo.update_post(
            post,
            **{f: getattr(payload, f) for f in spec.detail_fields},
        )
    return post
