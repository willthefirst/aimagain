"""Bespoke handlers for the `SavedSearch` sub-resource of `User`.

Only the **list** verb is bespoke. Create / update / delete / form
pages are framework-generic: those verbs gate write access by running
``write_authz`` (``assert_self_or_admin``) against the *parent* user
row inside the generic mounts (see
`src/framework/dispatch/mounts/{create,update,delete,form}.py`).

The generic list mount has no such per-parent gate — it would let any
authenticated viewer read ``/users/{other_id}/saved_searches`` — and a
saved search is private. So the list is hand-written with the same
self-or-admin gate `handle_list_user_clinicians` uses for the user's
clinician related-list.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import Request

from src.domain.logic.saved_searches.repository import SavedSearchRepository
from src.domain.models import SavedSearch, User
from src.framework.http.exceptions import ForbiddenError, NotFoundError


async def handle_list_saved_searches(
    request: Request,
    user_id: UUID,
    repo: SavedSearchRepository,
    requesting_user: User,
) -> dict[str, Any]:
    """`GET /users/{user_id}/saved_searches` — the owner's saved searches.

    Private: only the owner or an admin may read the list. Rows come
    back newest-first via ``BaseRepository.list_owned_by`` scoped on the
    ``user_id`` FK.
    """
    if user_id != requesting_user.id and not requesting_user.is_superuser:
        raise ForbiddenError(
            detail="Only the owner or an admin may view these saved searches"
        )
    owner = await repo.get_by_model_id(User, user_id)
    if owner is None:
        raise NotFoundError(detail=f"User {user_id} not found")
    rows = await repo.list_owned_by(SavedSearch, user_id, owner_attr="user_id")
    return {
        "request": request,
        "user": owner,
        "user_id": user_id,
        "rows": rows,
        "current_user": requesting_user,
        "is_self": user_id == requesting_user.id,
    }
