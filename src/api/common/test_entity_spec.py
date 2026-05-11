"""Tests for `EntitySpec` construction-time validation and bridging.

These assert the framework-level invariants — no entity is exercised
here. Per-entity correctness assertions (e.g. "user audit type is
'user'") live in `src/api/common/specs/test_<entity>.py`.
"""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

from src.api.common.entity_spec import (
    OWNER_OR_ADMIN,
    AuthzPolicy,
    EdgeAudit,
    EntitySpec,
    M2NRelation,
    Redirects,
    RouteSet,
    StateAxis,
    Templates,
)
from src.logic._authz import assert_owner_or_admin, is_owner_or_admin
from src.logic.audit import AuditAction, AuditedResource, make_snapshotter


class _DummyBody(BaseModel):
    flag: bool


class _DummyRead(BaseModel):
    """Same shape as `_DummyBody` but with `from_attributes` enabled so
    `model_validate` accepts ORM-like objects. Used by the read_schema
    tests; kept separate so the body-form tests keep checking the
    strict input shape."""

    flag: bool

    model_config = ConfigDict(from_attributes=True)


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


# --- New A4: EdgeAudit, M2NRelation, audit/edge_audit exclusivity --------


def _edge_audit() -> EdgeAudit:
    return EdgeAudit(
        resource_type="widget_edge",
        snapshot=lambda obj: {"id": "x"},
        actions={
            "add": AuditAction.ADD_FAVORITE,
            "remove": AuditAction.REMOVE_FAVORITE,
        },
    )


def test_edge_audit_action_for_verb():
    """`EdgeAudit.action_for(verb)` dispatches against the `actions` map."""
    edge = _edge_audit()
    assert edge.action_for("add") == AuditAction.ADD_FAVORITE
    assert edge.action_for("remove") == AuditAction.REMOVE_FAVORITE


def test_edge_audit_action_for_missing_verb_raises():
    """Asking for an unmapped verb is a programming error — KeyError loud."""
    edge = _edge_audit()
    with pytest.raises(KeyError):
        edge.action_for("update")


def test_edge_audit_and_audit_mutually_exclusive():
    """An entity is either CRUD-shaped or edge-shaped, not both."""
    with pytest.raises(ValueError, match="mutually exclusive"):
        _make_spec(audit=_dummy_audit(), edge_audit=_edge_audit())


def test_edge_audit_alone_constructs():
    spec = _make_spec(edge_audit=_edge_audit())
    assert spec.audit is None
    assert spec.edge_audit is not None


def test_m2n_relation_holds_endpoints_and_join_shape():
    user_spec = _make_spec(name="user", url_collection="users", id_param="user_id")
    provider_spec = _make_spec(
        name="provider", url_collection="providers", id_param="provider_id"
    )
    relation = M2NRelation(
        from_entity=user_spec,
        to_entity=provider_spec,
        join_table="user_favorites",
        from_attr="user_id",
        to_attr="provider_id",
    )
    spec = _make_spec(relation=relation)
    assert spec.relation is relation
    assert spec.relation.from_entity is user_spec
    assert spec.relation.to_entity is provider_spec
    assert spec.relation.join_table == "user_favorites"


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


def test_audit_snapshot_builds_audited_resource_from_schema():
    """`audit_snapshot=<schema>` triggers `make_audited_resource(name, schema)`
    at construction time so each CRUD entity doesn't repeat the call."""
    spec = _make_spec(
        name="user",  # picks the existing CREATE_USER/UPDATE_USER/DELETE_USER enum members
        audit_snapshot=_DummyBody,
    )
    assert spec.audit is not None
    assert spec.audit.type == "user"
    assert spec.audit.create == AuditAction.CREATE_USER
    assert spec.audit.update == AuditAction.UPDATE_USER
    assert spec.audit.delete == AuditAction.DELETE_USER


def test_audit_snapshot_and_audit_mutually_exclusive():
    with pytest.raises(ValueError, match="mutually exclusive"):
        _make_spec(audit=_dummy_audit(), audit_snapshot=_DummyBody)


def test_audit_action_stem_overrides_name():
    """Credential entities' enum stems diverge from `name` (e.g.
    `provider_licensure` → `CREATE_LICENSURE`). `audit_action_stem`
    feeds straight into `make_audited_resource`."""
    spec = _make_spec(
        name="provider_licensure",
        audit_snapshot=_DummyBody,
        audit_action_stem="licensure",
    )
    assert spec.audit.create == AuditAction.CREATE_LICENSURE


def test_read_schema_builds_projection_from_basemodel():
    """`read_schema=<BaseModel>` synthesizes a callable that validates
    through the schema and dumps a JSON-mode dict."""
    spec = _make_spec(read_schema=_DummyRead)
    assert spec.read_to_dict is not None
    projected = spec.read_to_dict(SimpleNamespace(flag=True))
    assert projected == {"flag": True}


def test_read_schema_builds_projection_from_type_adapter():
    """`read_schema=<TypeAdapter>` (for discriminated unions, e.g. posts)
    routes through `adapter.validate_python` instead."""
    adapter = TypeAdapter(_DummyRead)
    spec = _make_spec(read_schema=adapter)
    assert spec.read_to_dict is not None
    projected = spec.read_to_dict(SimpleNamespace(flag=False))
    assert projected == {"flag": False}


def test_read_schema_and_read_to_dict_mutually_exclusive():
    with pytest.raises(ValueError, match="mutually exclusive"):
        _make_spec(read_schema=_DummyRead, read_to_dict=lambda obj: {})


def test_audit_action_stem_without_snapshot_raises():
    """Setting the stem without a snapshot is a misconfiguration — the
    stem is only consumed when the constructor builds from a snapshot."""
    with pytest.raises(ValueError, match="audit_action_stem"):
        _make_spec(audit_action_stem="licensure")


def test_owner_or_admin_sentinel_pairs_assert_and_predicate():
    """The single import that specs grab. Pinning the pair here is the
    structural prevention that used to require a per-entity test."""
    assert OWNER_OR_ADMIN.write_authz is assert_owner_or_admin
    assert OWNER_OR_ADMIN.can_write is is_owner_or_admin


def test_auth_policy_expands_to_write_authz_and_can_write():
    """`auth_policy=POLICY` populates both fields with the matched callables."""
    spec = _make_spec(auth_policy=OWNER_OR_ADMIN)
    assert spec.write_authz is assert_owner_or_admin
    assert spec.can_write is is_owner_or_admin


def test_auth_policy_and_write_authz_mutually_exclusive():
    with pytest.raises(ValueError, match="mutually exclusive"):
        _make_spec(
            auth_policy=OWNER_OR_ADMIN,
            write_authz=assert_owner_or_admin,
        )


def test_auth_policy_and_can_write_mutually_exclusive():
    with pytest.raises(ValueError, match="mutually exclusive"):
        _make_spec(
            auth_policy=OWNER_OR_ADMIN,
            can_write=is_owner_or_admin,
        )


def test_custom_authz_policy_can_be_declared():
    """`AuthzPolicy` is a public dataclass — future rules (e.g. an
    `OWNER_ONLY` variant) just bind a new instance."""

    def _custom_assert(obj, user, **k):
        return None

    def _custom_can(obj, user):
        return True

    policy = AuthzPolicy(write_authz=_custom_assert, can_write=_custom_can)
    spec = _make_spec(auth_policy=policy)
    assert spec.write_authz is _custom_assert
    assert spec.can_write is _custom_can


def test_redirects_to_edit_form_picks_id_from_named_kwarg():
    """Reads `kwargs[id_param]` so the same callable serves owned
    subentities whose URL kwargs include both parent + own ids."""
    redirect = Redirects.to_edit_form("providers", "provider_id")
    assert (
        redirect(provider_id="abc-123", licensure_id="ignored")
        == "/providers/abc-123/form"
    )


def test_redirects_to_detail_formats_canonical_path():
    redirect = Redirects.to_detail("posts", "post_id")
    assert redirect(post_id="xyz-9") == "/posts/xyz-9"


def test_redirects_to_edit_form_missing_kwarg_raises_keyerror():
    """A misconfigured spec (wrong id_param) fails loudly at request
    time rather than silently producing a malformed URL."""
    redirect = Redirects.to_edit_form("providers", "provider_id")
    with pytest.raises(KeyError, match="provider_id"):
        redirect(some_other_id="abc")


def test_templates_default_by_convention_for_opted_in_verbs():
    """Each opted-in verb whose template path is unset gets
    ``<url_collection>/<verb>.html`` by convention."""
    spec = _make_spec(
        routes=RouteSet(list=True, detail=True),
    )
    assert spec.templates.list == "widgets/list.html"
    assert spec.templates.detail == "widgets/detail.html"
    # Non-opted-in verbs stay None — favorites relies on this for its
    # edge entity (routes all off, only `list` declared explicitly).
    assert spec.templates.form_new is None
    assert spec.templates.form_edit is None


def test_templates_explicit_overrides_convention():
    """An explicit template path is preserved verbatim."""
    spec = _make_spec(
        routes=RouteSet(list=True),
        templates=Templates(list="custom/list.html"),
    )
    assert spec.templates.list == "custom/list.html"


def test_templates_explicit_value_for_non_opted_in_verb_preserved():
    """Favorites declares `templates.list` without `routes.list=True` —
    the explicit declaration must not be wiped out by the default-only
    path."""
    spec = _make_spec(
        routes=RouteSet(),
        templates=Templates(list="favorites/list.html"),
    )
    assert spec.templates.list == "favorites/list.html"
    assert spec.templates.detail is None


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
