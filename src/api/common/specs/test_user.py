"""Spec-correctness suite for `USER_ENTITY`.

Asserts the spec declares the right things — not that CRUD works
(those tests live at the route/logic layers and stay until phase 2).
Each assertion proves that any layer reading from `USER_ENTITY` will
see the value it expects.
"""

from src.api.common.entity_spec import RelatedListSubresource, RouteSet
from src.api.common.specs.user import USER_ENTITY
from src.logic._authz import is_self_or_admin
from src.logic.audit import AuditAction
from src.models import User
from src.schemas.users.user import UserActivationUpdate

# --- Identity ------------------------------------------------------------


def test_identity_fields():
    assert USER_ENTITY.name == "user"
    assert USER_ENTITY.url_collection == "users"
    assert USER_ENTITY.id_param == "user_id"
    assert USER_ENTITY.model is User


def test_owner_attr_is_none():
    """Users aren't owned by another user — the resource *is* the user.
    `owner_attr=None` distinguishes them from `Provider`/`Post` which
    default to `"owner_id"`."""
    assert USER_ENTITY.owner_attr is None


# --- Audit binding -------------------------------------------------------


def test_audit_type_is_user():
    assert USER_ENTITY.audit is not None
    assert USER_ENTITY.audit.type == "user"


def test_audit_actions_match_crud_enum():
    assert USER_ENTITY.audit.create == AuditAction.CREATE_USER
    assert USER_ENTITY.audit.update == AuditAction.UPDATE_USER
    assert USER_ENTITY.audit.delete == AuditAction.DELETE_USER


# --- Visibility ----------------------------------------------------------


def test_private_fields_match_security_invariant():
    """The fields gated by the projection are exactly these three.
    Changing this tuple is a security-visible change — handler tests
    pin the runtime behavior."""
    assert USER_ENTITY.private_fields == ("email", "is_active", "is_verified")


def test_private_field_predicate_is_self_or_admin():
    assert USER_ENTITY.private_field_predicate is is_self_or_admin


# --- Routes opt-in -------------------------------------------------------


def test_routes_opted_in():
    """Users today exposes list, detail, and delete — confirmed against
    the mount calls in `src/api/routes/users.py`."""
    assert USER_ENTITY.routes == RouteSet(list=True, detail=True, delete=True)


# --- State axes ----------------------------------------------------------


def test_state_axes_has_exactly_activation():
    assert len(USER_ENTITY.state_axes) == 1
    axis = USER_ENTITY.state_axes[0]
    assert axis.name == "activation"


def test_activation_axis_shape():
    axis = USER_ENTITY.state_axis("activation")
    assert axis.body_schema is UserActivationUpdate
    assert axis.action == AuditAction.SET_USER_ACTIVATION
    # The route file consumes `response_to_dict` directly; pin its
    # shape so the wire response stays compatible.
    sample = axis.response_to_dict(
        type(
            "Sample",
            (),
            {"id": "abc-123", "username": "u", "is_active": True},
        )()
    )
    assert sample == {"id": "abc-123", "username": "u", "is_active": True}


# --- Subresources --------------------------------------------------------


def test_subresources_has_related_providers_with_me_alias():
    """`/users/{id}/providers` and `/users/me/providers` are the
    related-list — confirmed against `mount_related_list` in
    `src/api/routes/users.py`."""
    assert len(USER_ENTITY.subresources) == 1
    sub = USER_ENTITY.subresources[0]
    assert isinstance(sub, RelatedListSubresource)
    assert sub.child_spec.collection == "providers"
    assert sub.template == "users/providers_list.html"
    assert sub.singleton_alias is not None
    alias_segment, _alias_dep = sub.singleton_alias
    assert alias_segment == "me"


# --- Templates -----------------------------------------------------------


def test_templates():
    assert USER_ENTITY.templates.list == "users/list.html"
    assert USER_ENTITY.templates.detail == "users/detail.html"


# --- Bridge --------------------------------------------------------------


def test_to_resource_spec_round_trips_what_mounts_read():
    """The derived `ResourceSpec` must carry every field the existing
    `mount_*` functions read for users — collection, id_param,
    repo_dep, audit_resource, read/write user deps, list/detail
    templates, private_fields, predicate."""
    rs = USER_ENTITY.to_resource_spec()
    assert rs.collection == "users"
    assert rs.id_param == "user_id"
    assert rs.repo_dep is USER_ENTITY.repo_dep
    assert rs.audit_resource is USER_ENTITY.audit
    assert rs.read_user_dep is USER_ENTITY.read_user_dep
    assert rs.write_user_dep is USER_ENTITY.write_user_dep
    assert rs.list_template == "users/list.html"
    assert rs.detail_template == "users/detail.html"
    assert rs.private_fields == ("email", "is_active", "is_verified")
    assert rs.private_field_predicate is is_self_or_admin
