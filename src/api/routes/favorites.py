"""User-favorites routes — driven by `mount_edge_routes` against the
M:N edge spec. The three routes (list / add / remove) are synthesized
from `FAVORITE_ENTITY.relation`, `FAVORITE_ENTITY.templates.list`, and
the repo/user deps the spec declares; the route file no longer
restates path strings, status codes, or HX-Redirect targets.

Status-code shape (preserved across the refactor):
- POST returns 201 on first creation (with `Location` + `HX-Redirect`),
  200 on idempotent re-favorite (`HX-Refresh: true`; no relocation).
- DELETE returns 204 always — actual removal and no-op land at the
  same end state from the user's perspective.

Audit and commit are owned by the logic-layer handlers, not the mount
helper.
"""

import logging

from fastapi import APIRouter

from src.api.common import BaseRouter
from src.api.common.resource_routes import mount_edge_routes
from src.api.common.specs.user_favorite import FAVORITE_ENTITY
from src.logic.favorites.favorite_processing import (
    handle_add_favorite,
    handle_list_my_favorites,
    handle_remove_favorite,
)

favorites_api_router = APIRouter(prefix="/users/me/favorites")
router = BaseRouter(router=favorites_api_router, default_tags=["favorites"])
logger = logging.getLogger(__name__)


mount_edge_routes(
    router,
    FAVORITE_ENTITY,
    list_handler=handle_list_my_favorites,
    add_handler=handle_add_favorite,
    remove_handler=handle_remove_favorite,
)
