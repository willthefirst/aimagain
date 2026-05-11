import logging
from typing import Any

from fastapi import Request

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


async def post_list_extras(**_: Any) -> dict[str, Any]:
    """Per-list extras for `make_list_handler(POST_ENTITY)`. Includes the
    registered post kinds in the context so the list page can render its
    per-kind 'New X' links from a single source of truth."""
    return {"post_kinds": list(POST_KINDS.values())}


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
