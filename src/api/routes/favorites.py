"""User favorites routes — hand-rolled because the codebase has no
mount helper for M:N edge add/remove. The three routes are intentionally
self-only: the path prefix is fixed at `/users/me/favorites`, the actor
id is sourced from `current_active_user`, and there is no
`/users/{user_id}/favorites/...` parametric form. Admins do not see
other users' favorites in v1.

Status-code shape:
- POST returns 201 on first creation (with `Location` + `HX-Redirect`),
  200 on idempotent re-favorite (no relocation; the desired state already
  holds).
- DELETE returns 204 always — actual removal and no-op land at the same
  end state from the user's perspective.

Audit and commit are owned by the logic-layer handlers, not these route
shells.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from src.api.common import APIResponse, BaseRouter
from src.api.common.responses import (
    created_response,
    deleted_response,
    updated_response,
)
from src.auth_config import current_active_user
from src.logic.favorites.favorite_processing import (
    handle_add_favorite,
    handle_list_my_favorites,
    handle_remove_favorite,
)
from src.models import User
from src.repositories.audit_repository import AuditRepository
from src.repositories.dependencies import (
    get_audit_repository,
    get_provider_repository,
    get_user_favorite_repository,
)
from src.repositories.favorites.user_favorite_repository import UserFavoriteRepository
from src.repositories.providers.provider_repository import ProviderRepository

favorites_api_router = APIRouter(prefix="/users/me/favorites")
router = BaseRouter(router=favorites_api_router, default_tags=["favorites"])
logger = logging.getLogger(__name__)


@router.get("", name="favorites:list_my_favorites")
async def list_my_favorites(
    request: Request,
    user: User = Depends(current_active_user),
    repo: UserFavoriteRepository = Depends(get_user_favorite_repository),
):
    """Render the requesting user's favorites listing. Self-only; the
    /me path is the only entry point."""
    context = await handle_list_my_favorites(
        request=request, repo=repo, requesting_user=user
    )
    return APIResponse.html_response(
        template_name="favorites/list.html",
        context=context,
        request=request,
        current_user=user,
    )


@router.post("/{provider_id}", name="favorites:add_favorite")
async def add_favorite(
    provider_id: UUID,
    user: User = Depends(current_active_user),
    repo: UserFavoriteRepository = Depends(get_user_favorite_repository),
    provider_repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
):
    """Add a favorite edge. Idempotent: a duplicate POST returns 200
    with `HX-Refresh`, signalling the toggle UI to re-render. First
    creation returns 201 with the new edge id."""
    existing = await repo.get_by_pair(user_id=user.id, provider_id=provider_id)
    favorite = await handle_add_favorite(
        provider_id=provider_id,
        repo=repo,
        provider_repo=provider_repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    if existing is not None:
        return updated_response(body={"id": str(favorite.id)}, hx_refresh=True)
    return created_response(
        id=favorite.id,
        location=f"/providers/{provider_id}",
        hx_redirect=f"/providers/{provider_id}",
    )


@router.delete("/{provider_id}", name="favorites:remove_favorite")
async def remove_favorite(
    provider_id: UUID,
    user: User = Depends(current_active_user),
    repo: UserFavoriteRepository = Depends(get_user_favorite_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
):
    """Remove a favorite edge. Idempotent: 204 either way — the end
    state matches the user's intent regardless of prior edge state."""
    await handle_remove_favorite(
        provider_id=provider_id,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return deleted_response(hx_redirect=f"/providers/{provider_id}")
