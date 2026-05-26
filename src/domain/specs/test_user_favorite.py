"""Entity-specific facts for `FAVORITE_ENTITY` (M:N edge entity).

Universal invariants live in `test_spec_conformance.py`. This file pins
what's unique to favorites: the `EdgeAudit` verb→action map, the
`M2NRelation` endpoints and join-table shape, and the list-template
declaration (edges live outside `RouteSet`).
"""

from src.domain.specs.provider import PROVIDER_ENTITY
from src.domain.specs.user import USER_ENTITY
from src.domain.specs.user_favorite import FAVORITE_EDGE_AUDIT, FAVORITE_ENTITY
from src.framework.audit.core import AuditAction
from src.framework.dispatch.entity_spec import M2NRelation

# --- Audit binding (edge variant) ----------------------------------------


def test_edge_audit_identity():
    """The edge_audit lives at the module-level `FAVORITE_EDGE_AUDIT`
    binding so handlers can import it directly. Pinned identity rather
    than equality so a rebuild can't silently swap it."""
    assert FAVORITE_ENTITY.edge_audit is FAVORITE_EDGE_AUDIT


def test_edge_audit_actions():
    """Favorites has (add, remove), not (create, update, delete)."""
    assert FAVORITE_ENTITY.edge_audit.action_for("add") == AuditAction.ADD_FAVORITE
    assert (
        FAVORITE_ENTITY.edge_audit.action_for("remove") == AuditAction.REMOVE_FAVORITE
    )


def test_edge_audit_snapshot_callable():
    """Snapshot validates the row through `UserFavoriteAuditSnapshot`."""
    assert callable(FAVORITE_ENTITY.edge_audit.snapshot)


# --- Relation ------------------------------------------------------------


def test_relation_endpoints():
    assert FAVORITE_ENTITY.relation is not None
    assert FAVORITE_ENTITY.relation.from_entity is USER_ENTITY
    assert FAVORITE_ENTITY.relation.to_entity is PROVIDER_ENTITY


def test_relation_join_shape():
    assert FAVORITE_ENTITY.relation.join_table == "user_favorites"
    assert FAVORITE_ENTITY.relation.from_attr == "user_id"
    assert FAVORITE_ENTITY.relation.to_attr == "clinician_id"


def test_relation_is_M2NRelation():
    assert isinstance(FAVORITE_ENTITY.relation, M2NRelation)


# --- Edge entity templates ----------------------------------------------


def test_list_template_is_set_for_handrolled_route():
    """The route file is hand-rolled (`routes.list` stays False); the
    list template is read directly from the spec by `mount_edge_routes`.
    The conformance suite generalizes "templates.list set without
    routes.list True implies an M2NRelation"; this test pins the
    favorites-specific template name."""
    assert FAVORITE_ENTITY.templates.list == "favorites/list.html"
