"""User-favorites orchestration handlers.

A `UserFavorite` is a binary M:N edge between a `User` and a `Provider`.
There is no update verb — favorites are immutable edges — so the audit
discipline is satisfied via direct `record_audit(...)` calls rather than
the `mutate(...)` context manager (which assumes a create/update/delete
triple). Audit rows fire only on actual mutations: idempotent re-favorites
and idempotent un-favorites are silent.

Self-only: all three handlers operate on the requesting user's edges; the
route layer hard-codes the `/users/me/...` path prefix and sources the
user id from the session.
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import Request

from src.domain.logic.favorites.repository import UserFavoriteRepository
from src.domain.logic.providers.repository import ProviderRepository
from src.domain.models import Provider, User, UserFavorite
from src.domain.specs.user_favorite import FAVORITE_ENTITY
from src.framework.audit.core import record_audit
from src.framework.audit.repository import AuditRepository
from src.framework.http.exceptions import NotFoundError

logger = logging.getLogger(__name__)

# Audit binding (resource_type, snapshot, verb→action map) lives on
# the spec — see `src/domain/specs/user_favorite.py`. Handlers
# read it via `FAVORITE_ENTITY.edge_audit`.
_EDGE_AUDIT = FAVORITE_ENTITY.edge_audit


async def handle_add_favorite(
    provider_id: UUID,
    repo: UserFavoriteRepository,
    provider_repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> UserFavorite:
    """Add a favorite edge from the requesting user to `provider_id`.

    Idempotent: returns the existing edge unchanged if one already exists
    (no audit row, no commit). Audited only on actual creation.

    404 if the target provider does not exist — keeps the existence of a
    deleted provider opaque to the favorites endpoint.
    """
    provider = await provider_repo.get_by_model_id(Provider, provider_id)
    if provider is None:
        raise NotFoundError(detail="Provider not found")

    existing = await repo.get_by_pair(
        user_id=requesting_user.id, provider_id=provider_id
    )
    if existing is not None:
        return existing

    favorite = await repo.add_favorite(
        user_id=requesting_user.id, provider_id=provider_id
    )
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type=_EDGE_AUDIT.resource_type,
        resource_id=favorite.id,
        action=_EDGE_AUDIT.action_for("add"),
        before=None,
        after=_EDGE_AUDIT.snapshot(favorite),
    )
    await repo.session.commit()
    logger.info(f"Handler: user {requesting_user.id} favorited provider {provider_id}")
    return favorite


async def handle_remove_favorite(
    provider_id: UUID,
    repo: UserFavoriteRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> None:
    """Remove the favorite edge from the requesting user to `provider_id`.

    Idempotent: no-op (no audit row, no commit) if the edge does not exist.
    Audited only on actual deletion. No 404 if the user never favorited
    the provider — the user clicked "unfavorite" and the end state matches
    their intent.
    """
    favorite = await repo.get_by_pair(
        user_id=requesting_user.id, provider_id=provider_id
    )
    if favorite is None:
        return

    before = _EDGE_AUDIT.snapshot(favorite)
    favorite_id = favorite.id
    await repo.delete_favorite(favorite)
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type=_EDGE_AUDIT.resource_type,
        resource_id=favorite_id,
        action=_EDGE_AUDIT.action_for("remove"),
        before=before,
        after=None,
    )
    await repo.session.commit()
    logger.info(
        f"Handler: user {requesting_user.id} unfavorited provider {provider_id}"
    )


async def handle_list_my_favorites(
    request: Request,
    repo: UserFavoriteRepository,
    requesting_user: User,
) -> dict[str, Any]:
    """Page context for the self-only favorites listing. Returns the
    providers the requesting user has favorited, newest-favoriting first.
    """
    providers = await repo.list_favorited_providers(requesting_user.id)
    return {
        "request": request,
        "providers": providers,
        "current_user": requesting_user,
    }
