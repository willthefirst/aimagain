import logging
from uuid import UUID

from fastapi import Request

from src.api.common.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.logic.audit import AuditAction, record_audit
from src.models import (
    POST_KIND_CLIENT_REFERRAL,
    POST_KIND_PROVIDER_AVAILABILITY,
    ClientReferral,
    Post,
    ProviderAvailability,
    User,
)
from src.repositories.audit_repository import AuditRepository
from src.repositories.post_repository import PostRepository
from src.schemas.post import (
    ClientReferralCreate,
    ClientReferralUpdate,
    PostAuditSnapshot,
    PostCreate,
    PostUpdate,
    ProviderAvailabilityCreate,
)

logger = logging.getLogger(__name__)


_KIND_TO_MODEL: dict[str, type[Post]] = {
    POST_KIND_CLIENT_REFERRAL: ClientReferral,
    POST_KIND_PROVIDER_AVAILABILITY: ProviderAvailability,
}


def _snapshot_post(post: Post) -> dict:
    """Capture the user-meaningful fields of a post for audit before/after.

    Field set is defined by `PostAuditSnapshot` — adding a relevant field
    to that schema flows here automatically.
    """
    return PostAuditSnapshot.model_validate(post).model_dump(mode="json")


def _post_from_payload(payload: PostCreate, owner_id: UUID) -> Post:
    """Build the right `Post` subclass instance from a discriminated payload."""
    kwargs = payload.model_dump()
    kind = kwargs.pop("kind")
    model_cls = _KIND_TO_MODEL[kind]
    return model_cls(kind=kind, owner_id=owner_id, **kwargs)


async def handle_list_posts(
    request: Request,
    post_repo: PostRepository,
    requesting_user: User,
):
    """Loads all posts (newest first, every kind) and returns the template context."""
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
    requester is neither owner nor admin (mirrors `handle_update_post`).

    Per-kind template selection happens in the route layer.
    """
    post = await post_repo.get_post_by_id(post_id)
    if post is None:
        raise NotFoundError(detail="Post not found")

    if post.owner_id != requesting_user.id and not requesting_user.is_superuser:
        raise ForbiddenError(detail="Only the owner or an admin can edit this post")

    return {"request": request, "post": post, "current_user": requesting_user}


async def handle_create_post(
    payload: PostCreate,
    post_repo: PostRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> Post:
    """Creates a post (kind dispatched from the discriminated payload) owned by
    the requesting user; writes an audit row in the same transaction; commits
    on success.
    """
    post = _post_from_payload(payload, owner_id=requesting_user.id)
    created = await post_repo.create_post(post)
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
    logger.info(
        f"Handler: user {requesting_user.id} created {payload.kind} post {created.id}"
    )
    return created


async def handle_update_post(
    post_id: UUID,
    payload: PostUpdate,
    post_repo: PostRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> Post:
    """Patches a post owned by the requesting user (or by anyone, if the
    requester is a superuser). Writes an audit row capturing before/after
    snapshots in the same transaction; commits on success.

    Body's `kind` discriminator must match the persisted post's kind — a
    PATCH cannot repurpose a post's identity. 404 if missing, 403 if not
    authorized, 422 if the body's kind doesn't match or carries no edits.
    """
    post = await post_repo.get_post_by_id(post_id)
    if post is None:
        raise NotFoundError(detail="Post not found")

    if post.owner_id != requesting_user.id and not requesting_user.is_superuser:
        raise ForbiddenError(detail="Only the owner or an admin can edit this post")

    if payload.kind != post.kind:
        raise BadRequestError(
            detail=f"Body kind '{payload.kind}' does not match post kind '{post.kind}'"
        )

    before = _snapshot_post(post)
    update_fields = payload.model_dump(exclude={"kind"})
    updated = await post_repo.apply_post_update(post, **update_fields)
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


# `ClientReferralCreate`/`ProviderAvailabilityCreate` are re-exported so
# tests and tooling can construct payloads without reaching into schemas.
__all__ = [
    "ClientReferralCreate",
    "ClientReferralUpdate",
    "ProviderAvailabilityCreate",
    "handle_create_post",
    "handle_delete_post",
    "handle_get_post_detail",
    "handle_get_post_edit_form",
    "handle_get_post_form",
    "handle_list_posts",
    "handle_update_post",
]
