"""Tests guarding the post-kinds registry as the single source of truth.

The registry in `src/domain/models/posts/post_kinds.py` claims to drive every
cross-cutting site (model CHECK, detail-class lookup, per-kind
detail-relationship name). These tests assert that claim — if a
future change re-encodes the kind set inline somewhere, the relevant
test here fails.

(Pre-#628 the registry also drove the `/posts/form` `?kind=` Literal;
that route is gone now, each kind has its own URL family driving
form-template defaults via `spec.templates.form_new` instead.)
"""

from src.domain.models import (
    POST_KIND_BY_DETAIL_MODEL,
    POST_KIND_NAMES,
    POST_KINDS,
    Post,
)
from src.domain.models.posts.post_kinds import PostKindSpec
from src.domain.models.posts.referral_detail import ReferralDetail


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


def test_each_spec_detail_relationship_matches_kind_name():
    """Per-kind detail relationships follow the `<kind>_detail` convention
    except where the kind value was renamed but the SQL table / ORM
    relationship kept its historical name (renaming detail tables is
    migration noise with no payoff). Exceptions are pinned explicitly
    so a typo on a convention-following kind still gets caught."""
    relationship_exceptions = {
        # Rename `opening` → `clinician_opening` kept the historical
        # `opening_details` table and `opening_detail` relationship.
        "clinician_opening": "opening_detail",
        # Same for `intake` → `program_intake`.
        "program_intake": "intake_detail",
    }
    for kind, spec in POST_KINDS.items():
        expected = relationship_exceptions.get(kind, f"{kind}_detail")
        assert spec.detail_relationship == expected


def test_template_paths_default_by_convention():
    """`create_template` / `edit_template` are derived from the kind
    name when not explicitly set, following
    `posts/new_<name>.html` / `posts/edit_<name>.html`. Adding a kind
    therefore only needs the identity tuple — the template paths
    follow automatically.

    Exception: the two availability subkinds (`clinician_opening`,
    `program_intake`) live alongside the `/openings` URL collection's
    templates rather than under `posts/`, because they're owned by the
    `/openings` face end-to-end and the cross-resource import lint
    rejects `openings/<verb>.html` importing from `posts/`. The
    explicit overrides are pinned below."""
    expected_template_dirs = {
        "clinician_opening": "openings",
        "program_intake": "openings",
    }
    for kind, spec in POST_KINDS.items():
        dirname = expected_template_dirs.get(kind, "posts")
        assert spec.create_template == f"{dirname}/new_{kind}.html"
        assert spec.edit_template == f"{dirname}/edit_{kind}.html"


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
