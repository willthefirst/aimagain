"""Tests guarding the post-kinds registry as the single source of truth.

The registry in `src/domain/models/posts/post_kinds.py` claims to drive every
cross-cutting site (model CHECK, route Literal, form-template dicts,
detail-class lookup). These tests assert that claim — if a future
change re-encodes the kind set inline somewhere, the relevant test here
fails.
"""

from typing import get_args

from src.domain.models import (
    POST_KIND_BY_DETAIL_MODEL,
    POST_KIND_NAMES,
    POST_KINDS,
    Post,
)
from src.domain.models.posts.post_kinds import PostKindSpec
from src.domain.models.posts.referral_detail import ReferralDetail
from src.domain.routes import posts as posts_routes


def test_kind_names_matches_registered_kinds():
    """`POST_KIND_NAMES` is the registered-kinds dict's keys, in declaration order."""
    assert POST_KIND_NAMES == tuple(POST_KINDS)


def test_post_kinds_check_sql_matches_registry():
    """The CHECK SQL fragment lists exactly the registered kinds."""
    expected = "kind IN (" + ", ".join(repr(k) for k in POST_KIND_NAMES) + ")"
    assert POST_KINDS.check_sql() == expected


def test_post_check_constraint_uses_registry():
    """The `Post` model's CHECK constraint is derived from the registry, so
    its `sqltext` matches `POST_KINDS.check_sql()`. Guards against someone
    inlining a literal CHECK string that drifts from the registry."""
    constraints = [c for c in Post.__table__.constraints if c.name == "ck_posts_kind"]
    assert len(constraints) == 1
    # SQLAlchemy stores the CHECK as a TextClause; comparing the rendered SQL.
    rendered = str(constraints[0].sqltext.text)
    assert rendered == POST_KINDS.check_sql()


def test_kind_by_detail_model_inverse_matches_registry():
    """Every registered detail-model class is present in the inverse map,
    and the inverse map lookup returns the same spec as the forward
    registry."""
    assert {spec.detail_model for spec in POST_KINDS.values()} == set(
        POST_KIND_BY_DETAIL_MODEL
    )
    for spec in POST_KINDS.values():
        assert POST_KIND_BY_DETAIL_MODEL[spec.detail_model] is spec


def test_form_route_literal_matches_registry():
    """The `?kind=` Query parameter on `GET /posts/form` is typed as
    `Optional[Literal[*POST_KIND_NAMES]]` — the kind picker (`?kind=`
    absent / None) round-trips through the same route. Guards against
    `POST_KIND_NAMES` drifting from the route's accepted-kinds list."""
    import inspect

    routes = [r for r in posts_routes.router.router.routes if r.path == "/posts/form"]
    assert len(routes) == 1, "expected exactly one /posts/form route"
    params = inspect.signature(routes[0].endpoint).parameters
    # Optional[Literal[...]] → Union[Literal[...], None] → args are
    # (Literal[...], NoneType). Find the Literal arm and unwrap it.
    union_args = get_args(params["kind"].annotation)
    assert type(None) in union_args, "kind param should accept None (the picker)"
    literal_arm = next(a for a in union_args if a is not type(None))
    literal_values = get_args(literal_arm)
    assert set(literal_values) == set(POST_KIND_NAMES)


def test_each_spec_detail_relationship_matches_kind_name():
    """Per-kind detail relationships follow the `<kind>_detail` convention.
    This is convention, not enforcement — if a future kind needs a
    different relationship name, drop this test for that kind. But while
    every kind agrees, asserting it catches typos."""
    for kind, spec in POST_KINDS.items():
        assert spec.detail_relationship == f"{kind}_detail"


def test_template_paths_default_by_convention():
    """`create_template` / `edit_template` are derived from the kind
    name when not explicitly set, following
    `posts/new_<name>.html` / `posts/edit_<name>.html`. Adding a kind
    therefore only needs the identity tuple — the template paths
    follow automatically (the templates themselves still need to exist
    on disk, but the registry entry doesn't restate them)."""
    for kind, spec in POST_KINDS.items():
        assert spec.create_template == f"posts/new_{kind}.html"
        assert spec.edit_template == f"posts/edit_{kind}.html"


def test_explicit_template_paths_override_convention():
    """A spec that needs a non-conventional path can still declare one
    — passing `create_template="..."` skips the default."""
    spec = PostKindSpec(
        name="weird",
        detail_model=ReferralDetail,
        detail_relationship="weird_detail",
        detail_fields=(),
        list_label="weird",
        create_template="posts/custom_create.html",
    )
    # Override sticks; the unset edit_template still defaults.
    assert spec.create_template == "posts/custom_create.html"
    assert spec.edit_template == "posts/edit_weird.html"


def test_detail_fields_match_model_columns():
    """`PostKindSpec.detail_fields` is derived from the SQLAlchemy model's
    columns (minus the `post_id` PK/FK). This test asserts that
    contract: every non-`post_id` column on the detail table appears in
    `detail_fields`, in declaration order. Adding or dropping a column
    flows automatically; the alternative (a hand-maintained tuple in
    `post_kinds.py`) used to drift silently."""
    for spec in POST_KINDS.values():
        expected = tuple(
            c.name for c in spec.detail_model.__table__.columns if c.name != "post_id"
        )
        assert spec.detail_fields == expected
