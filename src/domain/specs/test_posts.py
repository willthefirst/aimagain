"""Pin tests for the `POST_ENTITY` whole-supertype spec.

`POST_ENTITY` is the codebase's only polymorphic entity, exposed at
`/posts` with three kinds (`referral`, `clinician_opening`,
`program_intake`). The tests here pin the whole-supertype shape:
neither `discriminator_value` nor `discriminator_values` set, the
discriminated-union adapters wired up, and the kind filter exposing
every registered kind on the list / search page.
"""

from src.domain.logic.posts.schema import (
    post_create_adapter,
    post_update_adapter,
)
from src.domain.models import POST_KINDS
from src.domain.specs.posts import POST_ENTITY


def test_post_entity_is_whole_supertype():
    """Whole-supertype: discriminator is set, but neither
    `discriminator_value` nor `discriminator_values` is. The list /
    search route is not bound to any kind subset; the create form's
    `?kind=` query param dispatches by row-level kind."""
    assert POST_ENTITY.discriminator is POST_KINDS
    assert POST_ENTITY.discriminator_value is None
    assert POST_ENTITY.discriminator_values is None


def test_post_entity_uses_discriminated_union_adapters():
    """The whole-supertype face wires the cross-kind union adapters
    directly — `post_create_adapter` accepts any kind, and the body's
    `kind` discriminator picks the matching per-kind variant."""
    assert POST_ENTITY.create_adapter is post_create_adapter
    assert POST_ENTITY.update_adapter is post_update_adapter
    assert POST_ENTITY.create_adapter_class is None
    assert POST_ENTITY.update_adapter_class is None


def test_post_entity_exposes_kind_filter_for_every_registered_kind():
    """The list / search page's `kind` filter has one choice per
    registered kind in `POST_KINDS` — the whole-supertype face lists
    every kind by default and the filter is the narrowing tool."""
    kind_filter = next(f for f in POST_ENTITY.filters if f.name == "kind")
    filter_values = {value for value, _label in kind_filter.choices}
    assert filter_values == set(POST_KINDS.names)


def test_post_entity_exposes_owner_me_radio_filter():
    """`?owner=me` is the viewer-relative scope filter powering the "My
    posts" view — a single-toggle radio (`multi=False`, `radio=True`)
    with exactly the `("me", …)` choice, mirroring the clinician/org
    owner filter. The repo resolves `owner="me"` to the viewer's own
    posts; the filter declaration is what makes the toggle render."""
    owner_filter = next(f for f in POST_ENTITY.filters if f.name == "owner")
    assert owner_filter.multi is False
    assert owner_filter.radio is True
    assert {value for value, _label in owner_filter.choices} == {"me"}


def test_post_entity_audit_resource_type_is_post():
    """Audit rows record `resource_type="post"` regardless of kind —
    the supertype shape is what survives across the polymorphic split."""
    assert POST_ENTITY.audit.type == "post"
