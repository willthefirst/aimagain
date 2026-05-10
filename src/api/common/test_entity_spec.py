"""Tests for `EntitySpec` construction-time validation and bridging.

These assert the framework-level invariants — no entity is exercised
here. Per-entity correctness assertions (e.g. "user audit type is
'user'") live in `src/api/common/specs/test_<entity>.py`.
"""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel, TypeAdapter

from src.api.common.entity_spec import (
    EntitySpec,
    RouteSet,
    StateAxis,
    Templates,
)
from src.logic.audit import AuditAction, AuditedResource, make_snapshotter


class _DummyBody(BaseModel):
    flag: bool


def _dummy_audit() -> AuditedResource:
    return AuditedResource(
        type="widget",
        snapshot=make_snapshotter(_DummyBody),
        create=AuditAction.CREATE_USER,  # any enum member; not exercised
        update=AuditAction.UPDATE_USER,
        delete=AuditAction.DELETE_USER,
    )


def _predicate(actor, target) -> bool:
    return False


def _make_spec(**overrides) -> EntitySpec:
    defaults = dict(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=SimpleNamespace,
    )
    defaults.update(overrides)
    return EntitySpec(**defaults)


def test_private_fields_without_predicate_raises():
    """Mirror of `ResourceSpec`'s guard — would silently leak fields."""
    with pytest.raises(ValueError, match="private_field_predicate"):
        _make_spec(private_fields=("secret",))


def test_private_fields_with_predicate_constructs():
    spec = _make_spec(
        private_fields=("secret",),
        private_field_predicate=_predicate,
    )
    assert spec.private_fields == ("secret",)
    assert spec.private_field_predicate is _predicate


def test_no_private_fields_no_predicate_constructs():
    spec = _make_spec()
    assert spec.private_fields == ()
    assert spec.private_field_predicate is None


def test_duplicate_state_axis_names_raises():
    """Two axes with the same name would shadow each other at mount time."""
    axis_a = StateAxis(
        name="activation",
        body_schema=_DummyBody,
        action=AuditAction.SET_USER_ACTIVATION,
    )
    axis_b = StateAxis(
        name="activation",
        body_schema=_DummyBody,
        action=AuditAction.UPDATE_USER,
    )
    with pytest.raises(ValueError, match="duplicate state-axis"):
        _make_spec(state_axes=(axis_a, axis_b))


def test_state_axis_lookup_by_name():
    axis = StateAxis(
        name="activation",
        body_schema=_DummyBody,
        action=AuditAction.SET_USER_ACTIVATION,
    )
    spec = _make_spec(state_axes=(axis,))
    assert spec.state_axis("activation") is axis


def test_state_axis_lookup_missing_raises():
    spec = _make_spec()
    with pytest.raises(KeyError, match="activation"):
        spec.state_axis("activation")


def test_default_route_set_disables_everything():
    """Empty `RouteSet` is the default; entities must opt in explicitly."""
    spec = _make_spec()
    assert spec.routes == RouteSet()
    assert not spec.routes.list
    assert not spec.routes.detail
    assert not spec.routes.delete
    assert not spec.routes.create
    assert not spec.routes.update
    assert not spec.routes.form_new
    assert not spec.routes.form_edit


def test_to_resource_spec_populates_every_bridged_field():
    """`to_resource_spec()` must round-trip every field the mount helpers read."""
    audit = _dummy_audit()
    repo_dep = lambda: None
    read_dep = lambda: None
    write_dep = lambda: None
    write_authz = lambda obj, user, **k: None
    create_adapter = TypeAdapter(_DummyBody)
    update_adapter = TypeAdapter(_DummyBody)
    read_to_dict = lambda obj: {"x": 1}
    create_redirect = lambda **k: "/x/create"
    update_redirect = lambda **k: "/x/update"
    delete_redirect = lambda **k: "/x/delete"
    spec = _make_spec(
        repo_dep=repo_dep,
        read_user_dep=read_dep,
        write_user_dep=write_dep,
        write_authz=write_authz,
        audit=audit,
        create_adapter=create_adapter,
        update_adapter=update_adapter,
        read_to_dict=read_to_dict,
        create_redirect=create_redirect,
        update_redirect=update_redirect,
        delete_redirect=delete_redirect,
        private_fields=("secret",),
        private_field_predicate=_predicate,
        templates=Templates(list="w/list.html", detail="w/detail.html"),
    )
    resource_spec = spec.to_resource_spec()

    assert resource_spec.collection == "widgets"
    assert resource_spec.id_param == "widget_id"
    assert resource_spec.repo_dep is repo_dep
    assert resource_spec.read_user_dep is read_dep
    assert resource_spec.write_user_dep is write_dep
    assert resource_spec.write_authz is write_authz
    assert resource_spec.audit_resource is audit
    assert resource_spec.create_adapter is create_adapter
    assert resource_spec.update_adapter is update_adapter
    assert resource_spec.read_to_dict is read_to_dict
    assert resource_spec.create_redirect is create_redirect
    assert resource_spec.update_redirect is update_redirect
    assert resource_spec.delete_redirect is delete_redirect
    assert resource_spec.private_fields == ("secret",)
    assert resource_spec.private_field_predicate is _predicate
    assert resource_spec.list_template == "w/list.html"
    assert resource_spec.detail_template == "w/detail.html"
    assert resource_spec.parent is None


def test_to_resource_spec_passes_through_none_audit_and_templates():
    """Resources without audit / templates derive a `ResourceSpec` whose
    corresponding fields are `None` — `ResourceSpec` permits that."""
    spec = _make_spec()
    resource_spec = spec.to_resource_spec()
    assert resource_spec.audit_resource is None
    assert resource_spec.list_template is None
    assert resource_spec.detail_template is None
    assert resource_spec.parent is None


# --- New A2 validations + parent-chain bridging --------------------------


def test_routes_create_requires_create_adapter():
    """A `routes.create=True` spec without a create adapter is a
    misconfiguration that would crash at first request — fail fast."""
    with pytest.raises(ValueError, match="create_adapter"):
        _make_spec(routes=RouteSet(create=True))


def test_routes_update_requires_update_adapter():
    with pytest.raises(ValueError, match="update_adapter"):
        _make_spec(routes=RouteSet(update=True))


def test_routes_create_with_adapter_constructs():
    spec = _make_spec(
        routes=RouteSet(create=True),
        create_adapter=TypeAdapter(_DummyBody),
    )
    assert spec.routes.create is True


def test_parent_without_routes_raises():
    """An owned subentity with no routes is unreachable — surface the
    misconfiguration at construction time."""
    parent = _make_spec(name="parent", url_collection="parents", id_param="parent_id")
    with pytest.raises(ValueError, match="unreachable"):
        _make_spec(
            name="child",
            url_collection="children",
            id_param="child_id",
            parent=parent,
            routes=RouteSet(),  # no routes opted in
        )


def test_parent_with_routes_constructs():
    parent = _make_spec(name="parent", url_collection="parents", id_param="parent_id")
    child = _make_spec(
        name="child",
        url_collection="children",
        id_param="child_id",
        parent=parent,
        routes=RouteSet(delete=True),
    )
    assert child.parent is parent


def test_discriminator_defaults_to_none():
    """Only polymorphic entities (posts) set this — others leave it as None."""
    spec = _make_spec()
    assert spec.discriminator is None


def test_discriminator_accepts_registry_instance():
    """`DiscriminatorRegistry` from `src.models._polymorphic` plugs in."""
    from src.models._polymorphic import DiscriminatorRegistry

    registry = DiscriminatorRegistry(
        column="kind", specs={"a": "spec-a", "b": "spec-b"}
    )
    spec = _make_spec(discriminator=registry)
    assert spec.discriminator is registry
    assert spec.discriminator.names == ("a", "b")


def test_to_resource_spec_walks_parent_chain():
    """`to_resource_spec()` on a child propagates the parent chain so
    the mount layer can build nested paths."""
    parent = _make_spec(name="parent", url_collection="parents", id_param="parent_id")
    child = _make_spec(
        name="child",
        url_collection="children",
        id_param="child_id",
        parent=parent,
        routes=RouteSet(delete=True),
    )
    child_rs = child.to_resource_spec()
    assert child_rs.parent is not None
    assert child_rs.parent.collection == "parents"
    assert child_rs.parent.id_param == "parent_id"
    # The walk is non-destructive: parent spec to_resource_spec
    # returns a fresh ResourceSpec each call (no caching needed for
    # phase 1).
    assert child_rs.parent.parent is None
