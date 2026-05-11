import logging
from uuid import UUID

from fastapi import Request

from src.api.common.exceptions import NotFoundError
from src.api.common.specs.post import POST_ENTITY
from src.models import POST_KINDS, User
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

    `can_edit` is the post's owner-or-admin predicate, read from
    `POST_ENTITY.can_write` so the rule lives in exactly one place
    (the spec); the asserting form on the same spec
    (`POST_ENTITY.write_authz`) gates mutations.
    """
    post = await repo.get_post_by_id(post_id)
    if post is None:
        raise NotFoundError(detail="Post not found")

    return {
        "request": request,
        "post": post,
        "current_user": requesting_user,
        "can_edit": POST_ENTITY.can_write(post, requesting_user),
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
