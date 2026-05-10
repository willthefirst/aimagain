"""`FAVORITE_ENTITY`: declaration of the user-favorites M:N edge.

UserFavorite is the codebase's only M:N edge entity. It has two
characteristics no prior entity exercised:

  1. **Non-CRUD verbs.** Favorites have ``(add, remove)`` verbs, not
     ``(create, update, delete)``. `AuditedResource` doesn't fit —
     `EdgeAudit` captures the binding instead. The two are mutually
     exclusive on `EntitySpec`; favorites uses `edge_audit`.
  2. **Many-to-many shape.** The `user_favorites` join table links
     `User` and `Provider`. `M2NRelation` captures the endpoints
     + join-table shape.

Phase 1 makes both declarations load-bearing: handlers in
`favorite_processing.py` read `resource_type`, `snapshot`, and the
verb→action map from `FAVORITE_ENTITY.edge_audit` instead of bespoke
module-level constants.

The route file (`src/api/routes/favorites.py`) stays hand-rolled —
the codebase has no `mount_edge_*` helper today and `RouteSet`'s
flags don't fit edge-shaped routes. Phase 2 may introduce edge
mount helpers later; A4 doesn't.
"""

from typing import Final

from src.api.common.entity_spec import (
    EdgeAudit,
    EntitySpec,
    M2NRelation,
    RouteSet,
    Templates,
)
from src.api.common.specs.provider import PROVIDER_ENTITY
from src.api.common.specs.user import USER_ENTITY
from src.auth_config import current_active_user
from src.logic.audit import AuditAction, make_snapshotter
from src.models import UserFavorite
from src.repositories.dependencies import get_user_favorite_repository
from src.schemas.favorites.user_favorite import UserFavoriteAuditSnapshot

FAVORITE_EDGE_AUDIT: Final[EdgeAudit] = EdgeAudit(
    resource_type="user_favorite",
    snapshot=make_snapshotter(UserFavoriteAuditSnapshot),
    actions={
        "add": AuditAction.ADD_FAVORITE,
        "remove": AuditAction.REMOVE_FAVORITE,
    },
)


FAVORITE_ENTITY: Final[EntitySpec] = EntitySpec(
    name="user_favorite",
    url_collection="favorites",
    # The edge has a UUID PK on `UserFavorite.id`; the route file's
    # URLs use `{provider_id}` (the to-side of the edge) instead. The
    # spec declares the entity's PK name; URL grammar is the route
    # file's bespoke concern.
    id_param="favorite_id",
    model=UserFavorite,
    repo_dep=get_user_favorite_repository,
    read_user_dep=current_active_user,
    write_user_dep=current_active_user,
    edge_audit=FAVORITE_EDGE_AUDIT,
    relation=M2NRelation(
        from_entity=USER_ENTITY,
        to_entity=PROVIDER_ENTITY,
        join_table="user_favorites",
        from_attr="user_id",
        to_attr="provider_id",
    ),
    # Favorites doesn't use any `mount_*` helper — the route file is
    # hand-rolled. All `RouteSet` flags stay False; phase 2 may
    # introduce edge-specific flags + mount helpers.
    routes=RouteSet(),
    templates=Templates(list="favorites/list.html"),
)
