import logging
from uuid import UUID

from fastapi import Request

from src.api.common.exceptions import BadRequestError, NotFoundError
from src.logic._authz import assert_owner_or_admin
from src.logic.audit import AuditAction, AuditedResource, mutate
from src.models import REGISTERED_KINDS, Post, User
from src.repositories.audit_repository import AuditRepository
from src.repositories.posts.post_repository import PostRepository
from src.schemas.posts.post import (
    ClientReferralCreate,
    ClientReferralUpdate,
    ProviderAvailabilityCreate,
    ProviderAvailabilityUpdate,
    post_audit_snapshot,
)

logger = logging.getLogger(__name__)

PostCreatePayload = ClientReferralCreate | ProviderAvailabilityCreate
PostUpdatePayload = ClientReferralUpdate | ProviderAvailabilityUpdate


POST = AuditedResource(
    type="post",
    snapshot=post_audit_snapshot,
    create=AuditAction.CREATE_POST,
    update=AuditAction.UPDATE_POST,
    delete=AuditAction.DELETE_POST,
)


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
        "post_kinds": list(REGISTERED_KINDS.values()),
    }


async def handle_get_post_detail(
    request: Request,
    post_id: UUID,
    repo: PostRepository,
    requesting_user: User,
):
    """Loads a single post for the detail page; 404s if missing."""
    post = await repo.get_post_by_id(post_id)
    if post is None:
        raise NotFoundError(detail="Post not found")

    return {"request": request, "post": post, "current_user": requesting_user}


async def handle_get_post_form(
    request: Request,
    requesting_user: User,
):
    """Builds the template context for the create-post form."""
    return {"request": request, "current_user": requesting_user}


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
        "template_name": REGISTERED_KINDS[post.kind].edit_template,
    }


async def handle_create_post(
    payload: PostCreatePayload,
    repo: PostRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> Post:
    """Creates a post owned by the requesting user; writes an audit row in
    the same transaction; commits on success.

    Dispatches via the `REGISTERED_KINDS` registry: the `kind` discriminator
    on the payload picks the spec, and the spec's `detail_model` +
    `detail_fields` build the right detail row. Adding a new kind means
    a registry entry — no edits here.
    """
    spec = REGISTERED_KINDS[payload.kind]
    post = Post(kind=payload.kind, owner_id=requesting_user.id)
    detail = spec.detail_model(**{f: getattr(payload, f) for f in spec.detail_fields})

    created = await repo.create_post(post, detail)
    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=created,
        resource=POST,
        verb="create",
    ):
        pass
    return created


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
    mismatch. Per-kind field set comes from `REGISTERED_KINDS`.
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

    spec = REGISTERED_KINDS[payload.kind]
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


async def handle_delete_post(
    post_id: UUID,
    repo: PostRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> None:
    """Hard-deletes a post owned by the requesting user (or any post, if the
    requester is a superuser). Writes an audit row capturing the pre-delete
    state in `before` (with `after=None`) in the same transaction; commits
    on success.

    404 if missing, 403 if not authorized.
    """
    post = await repo.get_post_by_id(post_id)
    if post is None:
        raise NotFoundError(detail="Post not found")

    assert_owner_or_admin(post, requesting_user, action="delete this post")

    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=post,
        resource=POST,
        verb="delete",
    ):
        await repo.delete_post(post)
