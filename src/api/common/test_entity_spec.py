"""Tests for `EntitySpec` construction-time validation and bridging.

These assert the framework-level invariants — no entity is exercised
here. Per-entity correctness assertions (e.g. "user audit type is
'user'") live in `src/api/common/specs/test_<entity>.py`.
"""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

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
    assert not spec.routes.form


def test_to_resource_spec_populates_every_bridged_field():
    """`to_resource_spec()` must round-trip every field the mount helpers read."""
    audit = _dummy_audit()
    repo_dep = lambda: None
    read_dep = lambda: None
    write_dep = lambda: None
    spec = _make_spec(
        repo_dep=repo_dep,
        read_user_dep=read_dep,
        write_user_dep=write_dep,
        audit=audit,
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
    assert resource_spec.audit_resource is audit
    assert resource_spec.private_fields == ("secret",)
    assert resource_spec.private_field_predicate is _predicate
    assert resource_spec.list_template == "w/list.html"
    assert resource_spec.detail_template == "w/detail.html"


def test_to_resource_spec_passes_through_none_audit_and_templates():
    """Resources without audit / templates derive a `ResourceSpec` whose
    corresponding fields are `None` — `ResourceSpec` permits that."""
    spec = _make_spec()
    resource_spec = spec.to_resource_spec()
    assert resource_spec.audit_resource is None
    assert resource_spec.list_template is None
    assert resource_spec.detail_template is None
