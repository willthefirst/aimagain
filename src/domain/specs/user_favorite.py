"""`FAVORITE_ENTITY`: declaration of the user-favorites M:N edge.

UserFavorite is the codebase's only M:N edge entity. It has two
characteristics no prior entity exercised:

  1. **Non-CRUD verbs.** Favorites have ``(add, remove)`` verbs, not
     ``(create, update, delete)``. `AuditedResource` doesn't fit —
     `EdgeAudit` captures the binding instead. The two are mutually
     exclusive on `EntitySpec`; favorites uses `edge_audit`.
  2. **Many-to-many shape.** The `user_favorites` join table links
     `User` and `Clinician`. `M2NRelation` captures the endpoints
     + join-table shape.

Phase 1 makes both declarations load-bearing: handlers in
`favorite_processing.py` read `resource_type`, `snapshot`, and the
verb→action map from `FAVORITE_ENTITY.edge_audit` instead of bespoke
module-level constants.

The route file (`src/domain/routes/favorites.py`) mounts the edge via
`mount_edge_routes`, passing only `add_handler`/`remove_handler` (no
`list_handler`) — so only the POST/DELETE toggle exists. There is no
favorites list page; favorited clinicians are browsed through the
`/clinicians?favorited=me` directory filter.
"""

from typing import Final

from src.domain.logic.favorites.repository import get_user_favorite_repository
from src.domain.logic.favorites.schema import UserFavoriteAuditSnapshot
from src.domain.models import UserFavorite
from src.domain.specs.clinician import CLINICIAN_ENTITY
from src.domain.specs.user import USER_ENTITY
from src.framework.audit.core import AuditAction, make_snapshotter
from src.framework.dispatch.entity_spec import (
    AUTHENTICATED,
    EdgeAudit,
    EntitySpec,
    M2NRelation,
    RouteSet,
)

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
    # URLs use `{clinician_id}` (the to-side of the edge) instead. The
    # spec declares the entity's PK name; URL grammar is the route
    # file's bespoke concern.
    id_param="favorite_id",
    model=UserFavorite,
    repo_dep=get_user_favorite_repository,
    auth_deps=AUTHENTICATED,
    edge_audit=FAVORITE_EDGE_AUDIT,
    relation=M2NRelation(
        from_entity=USER_ENTITY,
        to_entity=CLINICIAN_ENTITY,
        join_table="user_favorites",
        from_attr="user_id",
        to_attr="clinician_id",
    ),
    # Favorites mounts only the add/remove toggle via `mount_edge_routes`
    # (no `list_handler`), so there is no list page and no list template.
    # All `RouteSet` flags stay False — the edge routes are mounted
    # explicitly in `routes/favorites.py`. Favorited clinicians are
    # browsed via the `/clinicians?favorited=me` directory filter.
    routes=RouteSet(),
    # Favorites' URLs nest under the requesting user: the edge is
    # self-only and routes live at `/users/me/favorites/...` rather than
    # `/<url_collection>/...`. Every other entity leaves `prefix_override`
    # unset; the default is `f"/{url_collection}"`.
    prefix_override="/users/me/favorites",
)
