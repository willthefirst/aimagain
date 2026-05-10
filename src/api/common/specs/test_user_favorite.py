"""Spec-correctness suite for `FAVORITE_ENTITY`."""

from src.api.common.entity_spec import M2NRelation, RouteSet
from src.api.common.specs.provider import PROVIDER_ENTITY
from src.api.common.specs.user import USER_ENTITY
from src.api.common.specs.user_favorite import FAVORITE_EDGE_AUDIT, FAVORITE_ENTITY
from src.logic.audit import AuditAction
from src.models import UserFavorite

# --- Identity ------------------------------------------------------------


def test_identity_fields():
    assert FAVORITE_ENTITY.name == "user_favorite"
    assert FAVORITE_ENTITY.url_collection == "favorites"
    assert FAVORITE_ENTITY.id_param == "favorite_id"
    assert FAVORITE_ENTITY.model is UserFavorite


def test_owner_attr_defaults_to_owner_id():
    """Default applies even though favorites doesn't currently use it —
    the spec stays uniform across entities."""
    assert FAVORITE_ENTITY.owner_attr == "owner_id"


# --- Audit binding (edge variant) ----------------------------------------


def test_audit_is_none_edge_audit_is_set():
    """Favorites uses `edge_audit`, not `audit` — the two are mutually
    exclusive on `EntitySpec`."""
    assert FAVORITE_ENTITY.audit is None
    assert FAVORITE_ENTITY.edge_audit is FAVORITE_EDGE_AUDIT


def test_edge_audit_resource_type():
    assert FAVORITE_ENTITY.edge_audit.resource_type == "user_favorite"


def test_edge_audit_actions():
    assert FAVORITE_ENTITY.edge_audit.action_for("add") == AuditAction.ADD_FAVORITE
    assert (
        FAVORITE_ENTITY.edge_audit.action_for("remove") == AuditAction.REMOVE_FAVORITE
    )


def test_edge_audit_snapshot_callable():
    """Snapshot validates the row through `UserFavoriteAuditSnapshot`."""
    assert callable(FAVORITE_ENTITY.edge_audit.snapshot)


# --- Routes (all opt-out) ------------------------------------------------


def test_routes_all_disabled():
    """Favorites uses no `mount_*` helper; route file is hand-rolled."""
    assert FAVORITE_ENTITY.routes == RouteSet()


# --- Relation ------------------------------------------------------------


def test_relation_endpoints():
    assert FAVORITE_ENTITY.relation is not None
    assert FAVORITE_ENTITY.relation.from_entity is USER_ENTITY
    assert FAVORITE_ENTITY.relation.to_entity is PROVIDER_ENTITY


def test_relation_join_shape():
    assert FAVORITE_ENTITY.relation.join_table == "user_favorites"
    assert FAVORITE_ENTITY.relation.from_attr == "user_id"
    assert FAVORITE_ENTITY.relation.to_attr == "provider_id"


def test_relation_is_M2NRelation():
    assert isinstance(FAVORITE_ENTITY.relation, M2NRelation)


# --- Templates -----------------------------------------------------------


def test_templates():
    assert FAVORITE_ENTITY.templates.list == "favorites/list.html"
    assert FAVORITE_ENTITY.templates.detail is None
