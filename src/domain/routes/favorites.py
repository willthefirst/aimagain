"""User-favorites routes — driven by `mount_edge_routes` against the
M:N edge spec. Only the add/remove toggle is mounted (POST/DELETE on
`/users/me/favorites/{clinician_id}`); there is no favorites list page.
Favorited clinicians are browsed via the `/clinicians?favorited=me`
directory filter instead.

Status-code shape:
- POST returns 201 on first creation (with `Location` + `HX-Redirect`),
  200 on idempotent re-favorite (`HX-Refresh: true`; no relocation).
- DELETE returns 204 always — actual removal and no-op land at the
  same end state from the user's perspective.

Audit and commit are owned by the logic-layer handlers, not the mount
helper.
"""

from src.domain.logic.favorites.handlers import (
    handle_add_favorite,
    handle_remove_favorite,
)
from src.domain.specs.user_favorite import FAVORITE_ENTITY
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_edge_routes

router = register_entity(FAVORITE_ENTITY)


mount_edge_routes(
    router,
    FAVORITE_ENTITY,
    add_handler=handle_add_favorite,
    remove_handler=handle_remove_favorite,
)
