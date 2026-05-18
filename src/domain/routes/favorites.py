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

from src.domain.logic.favorites.handlers import (
    handle_add_favorite,
    handle_list_my_favorites,
    handle_remove_favorite,
)
from src.domain.specs.user_favorite import FAVORITE_ENTITY
from src.framework.dispatch.registry import register_entity
from src.framework.dispatch.resource_routes import mount_edge_routes

router = register_entity(FAVORITE_ENTITY)


mount_edge_routes(
    router,
    FAVORITE_ENTITY,
    list_handler=handle_list_my_favorites,
    add_handler=handle_add_favorite,
    remove_handler=handle_remove_favorite,
)
