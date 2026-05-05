"""Tests guarding the post-kinds registry as the single source of truth.

The registry in `src/models/post_kinds.py` claims to drive every
cross-cutting site (model CHECK, route Literal, form-template dicts,
detail-class lookup). These tests assert that claim — if a future
change re-encodes the kind set inline somewhere, the relevant test here
fails.
"""

from typing import get_args

from src.api.routes.posts import get_post_form
from src.models import (
    KIND_BY_DETAIL_MODEL,
    KIND_NAMES,
    REGISTERED_KINDS,
    Post,
    kind_check_sql,
)


def test_kind_names_matches_registered_kinds():
    """`KIND_NAMES` is the registered-kinds dict's keys, in declaration order."""
    assert KIND_NAMES == tuple(REGISTERED_KINDS)


def test_kind_check_sql_matches_registry():
    """The CHECK SQL fragment lists exactly the registered kinds."""
    expected = "kind IN (" + ", ".join(repr(k) for k in KIND_NAMES) + ")"
    assert kind_check_sql() == expected


def test_post_check_constraint_uses_registry():
    """The `Post` model's CHECK constraint is derived from the registry, so
    its `sqltext` matches `kind_check_sql()`. Guards against someone
    inlining a literal CHECK string that drifts from the registry."""
    constraints = [c for c in Post.__table__.constraints if c.name == "ck_posts_kind"]
    assert len(constraints) == 1
    # SQLAlchemy stores the CHECK as a TextClause; comparing the rendered SQL.
    rendered = str(constraints[0].sqltext.text)
    assert rendered == kind_check_sql()


def test_kind_by_detail_model_inverse_matches_registry():
    """Every registered detail-model class is present in the inverse map,
    and the inverse map lookup returns the same spec as the forward
    registry."""
    assert {spec.detail_model for spec in REGISTERED_KINDS.values()} == set(
        KIND_BY_DETAIL_MODEL
    )
    for spec in REGISTERED_KINDS.values():
        assert KIND_BY_DETAIL_MODEL[spec.detail_model] is spec


def test_form_route_literal_matches_registry():
    """The `?kind=` Query parameter on `GET /posts/form` is typed as
    `Literal[*KIND_NAMES]`; the FastAPI signature must reflect that."""
    annotations = get_post_form.__annotations__
    literal_args = get_args(annotations["kind"])
    assert set(literal_args) == set(KIND_NAMES)


def test_each_spec_template_paths_are_kind_namespaced():
    """Per-kind templates follow the `posts/new_<kind>.html` /
    `posts/edit_<kind>.html` convention, so a kind rename catches the
    template-rename in code review."""
    for kind, spec in REGISTERED_KINDS.items():
        assert spec.create_template == f"posts/new_{kind}.html"
        assert spec.edit_template == f"posts/edit_{kind}.html"


def test_each_spec_detail_relationship_matches_kind_name():
    """Per-kind detail relationships follow the `<kind>_detail` convention.
    This is convention, not enforcement — if a future kind needs a
    different relationship name, drop this test for that kind. But while
    every kind agrees, asserting it catches typos."""
    for kind, spec in REGISTERED_KINDS.items():
        assert spec.detail_relationship == f"{kind}_detail"
