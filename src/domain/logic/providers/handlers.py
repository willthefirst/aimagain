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

from src.domain.logic.favorites.repository import UserFavoriteRepository
from src.domain.logic.providers.repository import ProviderRepository
from src.domain.logic.users.repository import UserRepository
from src.domain.models import (
    Provider,
    User,
)
from src.framework.exceptions import ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)


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
    target_user = await user_repo.get_by_model_id(User, user_id)
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
