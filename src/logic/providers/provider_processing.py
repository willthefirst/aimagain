"""Provider-provider orchestration handlers.

One file per resource family — the parent provider plus its three credential
sub-tables (licensure, education, certification). Each mutation handler
owns the transaction commit and writes a single audit row covering the
mutation, per `RESOURCE_GRAMMAR.md:135` and the discipline enforced in
`test_audit_discipline.py`.

Authorization is uniform: a provider can mutate only their own provider and
its sub-rows; a superuser can mutate any. Read handlers are open to any
authenticated user.

Sub-resource handlers also assert that the URL's `provider_id` matches the
sub-row's `provider_id`. Without this, `/providers/A/licensures/B` would
silently mutate a licensure belonging to a different provider.
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import Request

# Importing the credential spec modules registers their `parent=PROVIDER_ENTITY`
# children on `PROVIDER_ENTITY.children` via the EntitySpec post-init
# registry — referenced by `handle_create_provider`'s inline-credential loop.
import src.api.common.specs.provider_certification  # noqa: F401
import src.api.common.specs.provider_education  # noqa: F401
import src.api.common.specs.provider_licensure  # noqa: F401
from src.api.common.exceptions import ForbiddenError, NotFoundError
from src.api.common.specs.provider import PROVIDER_ENTITY
from src.logic.audit import mutate
from src.models import (
    Provider,
    User,
)
from src.repositories.audit_repository import AuditRepository
from src.repositories.favorites.user_favorite_repository import UserFavoriteRepository
from src.repositories.providers.provider_repository import ProviderRepository
from src.repositories.users.user_repository import UserRepository
from src.schemas.providers.provider import (
    ProviderCreate,
)

logger = logging.getLogger(__name__)


# The audit binding lives on `PROVIDER_ENTITY.audit`; this re-export
# keeps the handler body's `resource=PROVIDER` shape without churn.
PROVIDER = PROVIDER_ENTITY.audit


# --- Provider handlers ----------------------------------------------------


async def provider_detail_extras(
    *,
    target: Provider,
    requesting_user: User | None,
    user_favorite_repo: UserFavoriteRepository,
    **_: Any,
) -> dict[str, Any]:
    """Per-viewer detail extras for `make_detail_handler(PROVIDER_ENTITY)`.

    `is_favorited` is a property of the (viewer, provider) pair, not of
    the provider — it lives in context, not on the model. Anonymous
    viewers (`requesting_user is None` for a hypothetical public detail)
    get `False` without a DB round-trip; today `PROVIDER_ENTITY.read_user_dep`
    forces auth, but the None-check keeps the helper safe if that ever
    changes.
    """
    if requesting_user is None:
        return {"is_favorited": False}
    return {
        "is_favorited": await user_favorite_repo.is_favorited(
            user_id=requesting_user.id, provider_id=target.id
        )
    }


async def handle_list_user_providers(
    request: Request,
    user_id: UUID,
    repo: ProviderRepository,
    user_repo: UserRepository,
    requesting_user: User,
) -> dict[str, Any]:
    """Returns the template context for the user-scoped provider
    list page. A user may view their own list; admins may view anyone's.
    404 if the target user does not exist; 403 if a non-admin requests
    another user's list.
    """
    if user_id != requesting_user.id and not requesting_user.is_superuser:
        raise ForbiddenError(
            detail="Only the target user or an admin may view their providers"
        )
    target_user = await user_repo.get_user_by_id(user_id)
    if target_user is None:
        raise NotFoundError(detail=f"User {user_id} not found")
    providers = await repo.list_for_user(user_id)
    return {
        "request": request,
        "target_user": target_user,
        "providers": providers,
        "is_self": user_id == requesting_user.id,
        "current_user": requesting_user,
    }


async def handle_get_provider_form(
    request: Request,
    requesting_user: User,
    repo: ProviderRepository | None = None,
) -> dict[str, Any]:
    """Builds the template context for the create-provider form.

    `repo` is accepted for uniformity with the mount_form contract (every
    form handler gets the resource's primary repo) but not used here —
    creating a provider doesn't need to load anything from the db.
    """
    del repo  # explicitly unused
    return {
        "request": request,
        "current_user": requesting_user,
        # `providers/form_new.html` calls `field_for(schema, ...)` against
        # this Pydantic class; pass it explicitly rather than via a
        # core-level Jinja global so schemas stay opt-in per template
        # (and core doesn't need to import schemas).
        "schema": ProviderCreate,
    }


async def handle_create_provider(
    payload: ProviderCreate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> Provider:
    """Creates a provider owned by the requesting user plus any inline
    credential sub-rows. A user may own zero, one, or many providers —
    nothing here rejects a second create. One `CREATE_PROVIDER`
    audit row is written whose `after` snapshot includes the inline
    sub-rows — the snapshot schema embeds the nested credential lists,
    so a single row captures the full create.
    """
    # Inline-credential kinds derive from the parent → children registry
    # on `PROVIDER_ENTITY`: each owned-credential spec registers itself
    # when its module is imported. Adding a fourth credential is now a
    # single new spec file — no edit here.
    inline_collections = tuple(
        child.url_collection for child in PROVIDER_ENTITY.children
    )
    provider_fields = payload.model_dump(exclude=set(inline_collections))
    created = await repo.create_provider(user_id=requesting_user.id, **provider_fields)

    for child in PROVIDER_ENTITY.children:
        for item in getattr(payload, child.url_collection):
            await repo.add_child(
                created, child.url_collection, child.model(**item.model_dump())
            )

    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=created,
        resource=PROVIDER,
        verb="create",
    ):
        pass
    return created
