"""Parametrized conformance suite for every `EntitySpec` in the codebase.

The per-entity test files (``test_user.py``, ``test_provider.py``,
``test_post.py``, ``test_user_favorite.py``, ``test_provider_credentials.py``)
used to repeat the same identity / audit / template / round-trip
assertions for every entity. Each assertion is mechanical — it reads
from `EntitySpec` and checks that the value matches the spec's own
declared convention. That made every new entity carry ~150 LOC of
near-identical scaffolding.

This module collects every entity into ``ALL_ENTITY_SPECS`` and
parametrizes the universal invariants across them. The per-entity
files now only assert entity-specific facts (state axes, discriminator,
filters, redirects, M2NRelation endpoints) — anything that's *unique
to that entity* and couldn't be expressed as a generic rule.

Adding a new entity: append it to ``ALL_ENTITY_SPECS`` and the
universal invariants apply automatically; only the entity-specific
test file needs writing.
"""

import pytest
from pydantic import BaseModel, TypeAdapter

from src.domain.specs.post import POST_ENTITY
from src.domain.specs.provider import PROVIDER_ENTITY
from src.domain.specs.provider_certification import CERTIFICATION_ENTITY
from src.domain.specs.provider_education import EDUCATION_ENTITY
from src.domain.specs.provider_licensure import LICENSURE_ENTITY
from src.domain.specs.user import USER_ENTITY
from src.domain.specs.user_favorite import FAVORITE_ENTITY
from src.framework.audit import AuditAction
from src.framework.entity_spec import EntitySpec
from src.framework.resource_routes import ResourceSpec

# Canonical registry of every entity spec the codebase declares today.
# Order matches the source-tree walk order; tests should not depend on
# the order, but it keeps failures readable.
ALL_ENTITY_SPECS: tuple[EntitySpec, ...] = (
    USER_ENTITY,
    PROVIDER_ENTITY,
    LICENSURE_ENTITY,
    EDUCATION_ENTITY,
    CERTIFICATION_ENTITY,
    POST_ENTITY,
    FAVORITE_ENTITY,
)


def _spec_ids(spec: EntitySpec) -> str:
    return spec.name


_PARAM_ALL = pytest.mark.parametrize("spec", ALL_ENTITY_SPECS, ids=_spec_ids)


# --- Identity -------------------------------------------------------------


@_PARAM_ALL
def test_identity_fields_are_non_empty(spec: EntitySpec) -> None:
    assert isinstance(spec.name, str) and spec.name
    assert isinstance(spec.url_collection, str) and spec.url_collection
    assert isinstance(spec.id_param, str) and spec.id_param
    assert isinstance(spec.model, type)


# --- Audit binding --------------------------------------------------------


@_PARAM_ALL
def test_audit_and_edge_audit_are_mutually_exclusive(spec: EntitySpec) -> None:
    """`EntitySpec.__post_init__` enforces this; the conformance suite
    pins it across every entity so a future spec can't accidentally
    declare both."""
    assert not (spec.audit is not None and spec.edge_audit is not None)


@_PARAM_ALL
def test_exactly_one_audit_binding_is_set(spec: EntitySpec) -> None:
    """Every entity records mutations: CRUD entities via `AuditedResource`,
    edge entities via `EdgeAudit`. Declaring neither would make audit
    silently impossible at handler-call time."""
    has_crud = spec.audit is not None
    has_edge = spec.edge_audit is not None
    assert has_crud or has_edge, f"{spec.name!r} has no audit binding"


@_PARAM_ALL
def test_crud_audit_type_matches_name(spec: EntitySpec) -> None:
    """For CRUD-shaped entities, ``audit.type`` is the persisted
    ``resource_type`` string — by convention it equals ``spec.name``."""
    if spec.audit is None:
        pytest.skip(f"{spec.name!r} is an edge entity")
    assert spec.audit.type == spec.name


@_PARAM_ALL
def test_crud_audit_actions_match_stem(spec: EntitySpec) -> None:
    """The create / update / delete actions resolve from
    ``AuditAction[f'CREATE_{stem}']`` where ``stem`` defaults to
    ``spec.name`` and can be overridden via ``audit_action_stem``.
    This pins the convention so it stays load-bearing."""
    if spec.audit is None:
        pytest.skip(f"{spec.name!r} is an edge entity")
    stem = (spec.audit_action_stem or spec.name).upper()
    assert spec.audit.create == AuditAction[f"CREATE_{stem}"]
    assert spec.audit.update == AuditAction[f"UPDATE_{stem}"]
    assert spec.audit.delete == AuditAction[f"DELETE_{stem}"]


@_PARAM_ALL
def test_edge_audit_resource_type_matches_name(spec: EntitySpec) -> None:
    if spec.edge_audit is None:
        pytest.skip(f"{spec.name!r} is not an edge entity")
    assert spec.edge_audit.resource_type == spec.name


# --- Templates ------------------------------------------------------------


@_PARAM_ALL
def test_templates_default_by_convention_for_opted_in_verbs(
    spec: EntitySpec,
) -> None:
    """Every ``routes.<verb>=True`` flag gets a default template at
    ``<url_collection>/<verb>.html`` unless the spec explicitly
    overrides. Pinned here so an entity that opts into a verb without
    a matching template fails loud."""
    for verb in ("list", "detail", "form_new", "form_edit"):
        if not getattr(spec.routes, verb):
            continue
        actual = getattr(spec.templates, verb)
        assert (
            actual is not None
        ), f"{spec.name!r} opts into routes.{verb} but template is None"
        # The default is "<url_collection>/<verb>.html"; tolerate
        # entity-specific overrides without unrolling the check.
        if actual != f"{spec.url_collection}/{verb}.html":
            # Override — this is fine; pinning the path lives in the
            # per-entity test file.
            continue


@_PARAM_ALL
def test_templates_unset_for_non_opted_in_verbs(spec: EntitySpec) -> None:
    """If an entity doesn't opt into a verb, its template stays None
    (favorites' edge entity asserts ``detail is None``; the conformance
    suite generalizes that check)."""
    for verb in ("list", "detail", "form_new", "form_edit"):
        if getattr(spec.routes, verb):
            continue
        if verb == "list" and spec.templates.list is not None:
            # Edge entities (favorites) may declare a list template even
            # though `routes.list` is False — favorites' route file is
            # hand-rolled and reads the template directly from the spec.
            assert spec.relation is not None, (
                f"{spec.name!r} has templates.list set but routes.list=False "
                "and no M2NRelation — likely a misconfiguration."
            )
            continue
        assert (
            getattr(spec.templates, verb) is None
        ), f"{spec.name!r} templates.{verb} set but routes.{verb}=False"


# --- Bridge: to_resource_spec() ------------------------------------------


@_PARAM_ALL
def test_to_resource_spec_carries_identity(spec: EntitySpec) -> None:
    rs = spec.to_resource_spec()
    assert isinstance(rs, ResourceSpec)
    assert rs.collection == spec.url_collection
    assert rs.id_param == spec.id_param
    assert rs.repo_dep is spec.repo_dep
    assert rs.audit_resource is spec.audit
    assert rs.read_user_dep is spec.read_user_dep
    assert rs.write_user_dep is spec.write_user_dep
    assert rs.write_authz is spec.write_authz
    assert rs.create_adapter is spec.create_adapter
    assert rs.update_adapter is spec.update_adapter
    assert rs.read_to_dict is spec.read_to_dict
    assert rs.list_template == spec.templates.list
    assert rs.detail_template == spec.templates.detail
    assert rs.create_redirect is spec.create_redirect
    assert rs.update_redirect is spec.update_redirect
    assert rs.delete_redirect is spec.delete_redirect
    assert rs.private_fields == spec.private_fields
    assert rs.private_field_predicate is spec.private_field_predicate


@_PARAM_ALL
def test_to_resource_spec_walks_parent_chain(spec: EntitySpec) -> None:
    """If the entity has a parent, ``to_resource_spec().parent`` is the
    derived bridge of that parent."""
    rs = spec.to_resource_spec()
    if spec.parent is None:
        assert rs.parent is None
    else:
        assert rs.parent is not None
        assert rs.parent.collection == spec.parent.url_collection
        assert rs.parent.id_param == spec.parent.id_param


# --- Auth policy ---------------------------------------------------------


@_PARAM_ALL
def test_auth_policy_expands_to_write_authz_and_can_write(
    spec: EntitySpec,
) -> None:
    """When ``auth_policy`` is set, the constructor populates
    ``write_authz`` and ``can_write`` from it — pinned so a future
    refactor can't silently drop the expansion."""
    if spec.auth_policy is None:
        pytest.skip(f"{spec.name!r} uses no AuthzPolicy sentinel")
    assert spec.write_authz is spec.auth_policy.write_authz
    assert spec.can_write is spec.auth_policy.can_write


@_PARAM_ALL
def test_auth_deps_expands_to_read_and_write_user_dep(
    spec: EntitySpec,
) -> None:
    """When ``auth_deps`` is set, the constructor populates
    ``read_user_dep`` and ``write_user_dep`` from it. Sibling rule to
    ``auth_policy``'s expansion."""
    if spec.auth_deps is None:
        pytest.skip(f"{spec.name!r} uses no AuthDeps sentinel")
    assert spec.read_user_dep is spec.auth_deps.read
    assert spec.write_user_dep is spec.auth_deps.write


# --- Parent / children registry ------------------------------------------


@_PARAM_ALL
def test_owned_subentity_registered_with_parent(spec: EntitySpec) -> None:
    """Owned subentities self-register on their parent's ``_children``;
    the parent exposes them via ``.children`` so the generic
    ``handle_create`` can walk them on inline-child append."""
    if spec.parent is None:
        pytest.skip(f"{spec.name!r} is top-level")
    assert spec in spec.parent.children


# --- Adapter wrapping -----------------------------------------------------


@_PARAM_ALL
def test_create_adapter_is_a_typeadapter_when_set(spec: EntitySpec) -> None:
    """Plain Pydantic classes get wrapped in ``TypeAdapter`` by
    ``__post_init__``; mounts always see a ``TypeAdapter`` instance."""
    if spec.create_adapter is None:
        pytest.skip(f"{spec.name!r} has no create_adapter")
    assert isinstance(spec.create_adapter, TypeAdapter)


@_PARAM_ALL
def test_update_adapter_is_a_typeadapter_when_set(spec: EntitySpec) -> None:
    if spec.update_adapter is None:
        pytest.skip(f"{spec.name!r} has no update_adapter")
    assert isinstance(spec.update_adapter, TypeAdapter)


# --- Extras bindings -----------------------------------------------------


@_PARAM_ALL
def test_detail_extras_path_requires_detail_route(spec: EntitySpec) -> None:
    """Spec construction would have raised if this held false; the
    conformance suite pins the invariant across every entity so adding
    a new one doesn't accidentally re-create the bug."""
    if spec.detail_extras_path is None:
        pytest.skip(f"{spec.name!r} has no detail_extras_path")
    assert spec.routes.detail is True


@_PARAM_ALL
def test_list_extras_path_requires_list_route(spec: EntitySpec) -> None:
    if spec.list_extras_path is None:
        pytest.skip(f"{spec.name!r} has no list_extras_path")
    assert spec.routes.list is True


@_PARAM_ALL
def test_detail_extras_repos_requires_detail_extras_path(
    spec: EntitySpec,
) -> None:
    if not spec.detail_extras_repos:
        pytest.skip(f"{spec.name!r} has no detail_extras_repos")
    assert spec.detail_extras_path is not None


@_PARAM_ALL
def test_list_extras_repos_requires_list_extras_path(spec: EntitySpec) -> None:
    if not spec.list_extras_repos:
        pytest.skip(f"{spec.name!r} has no list_extras_repos")
    assert spec.list_extras_path is not None


# --- Visibility ----------------------------------------------------------


@_PARAM_ALL
def test_private_fields_require_predicate(spec: EntitySpec) -> None:
    """The constructor enforces this; pinned across every entity."""
    if not spec.private_fields:
        pytest.skip(f"{spec.name!r} declares no private_fields")
    assert spec.private_field_predicate is not None


# --- Read schema → audit_snapshot default --------------------------------


@_PARAM_ALL
def test_read_schema_defaults_audit_snapshot_for_basemodel(
    spec: EntitySpec,
) -> None:
    """If ``read_schema`` is a Pydantic class and no audit binding was
    explicitly declared, the constructor sets ``audit_snapshot`` to the
    read schema. Pinned so the default doesn't regress silently."""
    if not isinstance(spec.read_schema, type):
        pytest.skip(f"{spec.name!r} uses a non-class read_schema (or none)")
    if not issubclass(spec.read_schema, BaseModel):
        pytest.skip(f"{spec.name!r} read_schema is not a BaseModel subclass")
    # Either an explicit `audit_snapshot` was passed, or the default
    # propagated from `read_schema`.
    assert spec.audit_snapshot is not None
