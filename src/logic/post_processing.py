import logging
from uuid import UUID

from fastapi import Request

from src.api.common.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.logic.audit import AuditAction, record_audit
from src.models import (
    ClientReferralDetail,
    Post,
    ProviderAvailabilityDetail,
    User,
)
from src.repositories.audit_repository import AuditRepository
from src.repositories.post_repository import PostRepository
from src.schemas.post import (
    ClientReferralCreate,
    ClientReferralUpdate,
    ProviderAvailabilityCreate,
    ProviderAvailabilityUpdate,
    post_audit_snapshot,
)

logger = logging.getLogger(__name__)


def _snapshot_post(post: Post) -> dict:
    """Capture the user-meaningful fields of a post for audit before/after.

    The kind-specific projection lives in `src/schemas/post.py`; this is
    a thin alias so callers don't reach into the schemas layer for an
    audit-only helper.
    """
    return post_audit_snapshot(post)


async def handle_list_posts(
    request: Request,
    post_repo: PostRepository,
    requesting_user: User,
):
    """Loads all posts (newest first) and returns the template context."""
    posts = await post_repo.list_posts()
    return {"request": request, "posts": posts, "current_user": requesting_user}


async def handle_get_post_detail(
    request: Request,
    post_id: UUID,
    post_repo: PostRepository,
    requesting_user: User,
):
    """Loads a single post for the detail page; 404s if missing."""
    post = await post_repo.get_post_by_id(post_id)
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
    post_repo: PostRepository,
    requesting_user: User,
):
    """Loads a post for the edit-form page. 404 if missing, 403 if the
    requester is neither owner nor admin (mirrors `handle_update_post`)."""
    post = await post_repo.get_post_by_id(post_id)
    if post is None:
        raise NotFoundError(detail="Post not found")

    if post.owner_id != requesting_user.id and not requesting_user.is_superuser:
        raise ForbiddenError(detail="Only the owner or an admin can edit this post")

    return {"request": request, "post": post, "current_user": requesting_user}


async def handle_create_post(
    payload: ClientReferralCreate | ProviderAvailabilityCreate,
    post_repo: PostRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> Post:
    """Creates a post owned by the requesting user; writes an audit row in
    the same transaction; commits on success.

    Dispatches on `payload.kind` (set by the discriminated union in
    `src/schemas/post.py`) to build the right per-kind detail row. New
    kinds add a branch here.
    """
    if isinstance(payload, ClientReferralCreate):
        post = Post(kind="client_referral", owner_id=requesting_user.id)
        detail = ClientReferralDetail(description=payload.description)
    elif isinstance(payload, ProviderAvailabilityCreate):
        post = Post(kind="provider_availability", owner_id=requesting_user.id)
        detail = ProviderAvailabilityDetail(practice_name=payload.practice_name)
    else:  # pragma: no cover — schema discriminator should make this unreachable
        raise BadRequestError(detail=f"unsupported post kind: {payload.kind!r}")

    created = await post_repo.create_post(post, detail)
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type="post",
        resource_id=created.id,
        action=AuditAction.CREATE_POST,
        before=None,
        after=_snapshot_post(created),
    )
    await post_repo.session.commit()
    logger.info(f"Handler: user {requesting_user.id} created post {created.id}")
    return created


async def handle_update_post(
    post_id: UUID,
    payload: ClientReferralUpdate | ProviderAvailabilityUpdate,
    post_repo: PostRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> Post:
    """Patches a post owned by the requesting user (or by anyone, if the
    requester is a superuser). Writes an audit row capturing before/after
    snapshots in the same transaction; commits on success.

    The payload's `kind` must match the persisted post's `kind` — `kind`
    is part of the resource identity once created and cannot be migrated
    via PATCH. 404 if missing, 403 if not authorized, 400 on kind
    mismatch.
    """
    post = await post_repo.get_post_by_id(post_id)
    if post is None:
        raise NotFoundError(detail="Post not found")

    if post.owner_id != requesting_user.id and not requesting_user.is_superuser:
        raise ForbiddenError(detail="Only the owner or an admin can edit this post")

    if payload.kind != post.kind:
        raise BadRequestError(
            detail=(
                f"payload kind {payload.kind!r} does not match post kind "
                f"{post.kind!r}; kind cannot be changed via PATCH"
            )
        )

    before = _snapshot_post(post)
    if isinstance(payload, ClientReferralUpdate):
        updated = await post_repo.update_post(post, description=payload.description)
    else:  # ProviderAvailabilityUpdate
        updated = await post_repo.update_post(post, practice_name=payload.practice_name)
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type="post",
        resource_id=updated.id,
        action=AuditAction.UPDATE_POST,
        before=before,
        after=_snapshot_post(updated),
    )
    await post_repo.session.commit()
    logger.info(f"Handler: user {requesting_user.id} updated post {updated.id}")
    return updated


async def handle_delete_post(
    post_id: UUID,
    post_repo: PostRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> None:
    """Hard-deletes a post owned by the requesting user (or any post, if the
    requester is a superuser). Writes an audit row capturing the pre-delete
    state in `before` (with `after=None`) in the same transaction; commits
    on success.

    404 if missing, 403 if not authorized.
    """
    post = await post_repo.get_post_by_id(post_id)
    if post is None:
        raise NotFoundError(detail="Post not found")

    if post.owner_id != requesting_user.id and not requesting_user.is_superuser:
        raise ForbiddenError(detail="Only the owner or an admin can delete this post")

    before = _snapshot_post(post)
    target_id = post.id
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type="post",
        resource_id=target_id,
        action=AuditAction.DELETE_POST,
        before=before,
        after=None,
    )
    await post_repo.delete_post(post)
    await post_repo.session.commit()
    logger.info(f"Handler: user {requesting_user.id} deleted post {target_id}")
