"""Entity-specific facts for `USER_ENTITY`.

The universal invariants (identity field shapes, audit-type-matches-name,
templates default by convention, `to_resource_spec()` round-trips, etc.)
live in `test_spec_conformance.py` parametrized across every spec. This
file only pins what's unique to the user spec — the activation state
axis, the providers related-list, the private-fields tuple, the
`/users/me` singleton alias, and the per-viewer detail extras binding.
"""

from src.api.common.entity_spec import RelatedListSubresource
from src.api.common.specs.user import USER_ENTITY
from src.logic._authz import is_self_or_admin
from src.logic.audit import AuditAction
from src.schemas.users.user import UserActivationUpdate

# --- Visibility (security-visible) ---------------------------------------


def test_private_fields_match_security_invariant():
    """The fields gated by the projection are exactly these three.
    Changing this tuple is a security-visible change — handler tests
    pin the runtime behavior."""
    assert USER_ENTITY.private_fields == ("email", "is_active", "is_verified")


def test_private_field_predicate_is_self_or_admin():
    assert USER_ENTITY.private_field_predicate is is_self_or_admin


# --- Owner-attr semantics (user-specific) --------------------------------


def test_owner_attr_is_none():
    """Users aren't owned by another user — the resource *is* the user.
    `owner_attr=None` distinguishes them from `Provider`/`Post` which
    default to `"owner_id"`."""
    assert USER_ENTITY.owner_attr is None


# --- State axes ----------------------------------------------------------


def test_activation_axis_shape():
    axis = USER_ENTITY.state_axis("activation")
    assert axis.body_schema is UserActivationUpdate
    assert axis.action == AuditAction.SET_USER_ACTIVATION
    sample = axis.response_to_dict(
        type(
            "Sample",
            (),
            {"id": "abc-123", "username": "u", "is_active": True},
        )()
    )
    assert sample == {"id": "abc-123", "username": "u", "is_active": True}


def test_state_axes_has_exactly_activation():
    assert tuple(a.name for a in USER_ENTITY.state_axes) == ("activation",)


# --- Subresources --------------------------------------------------------


def test_subresources_has_related_providers_with_me_alias():
    """`/users/{id}/providers` and `/users/me/providers` are the
    related-list — confirmed against the mount calls in
    `src/api/routes/users.py`."""
    assert len(USER_ENTITY.subresources) == 1
    sub = USER_ENTITY.subresources[0]
    assert isinstance(sub, RelatedListSubresource)
    assert sub.child_spec.collection == "providers"
    assert sub.template == "users/providers_list.html"
    assert sub.singleton_alias is not None
    alias_segment, _alias_dep = sub.singleton_alias
    assert alias_segment == "me"


def test_singleton_alias_is_me():
    """`/users/me` detail route — id sourced from session."""
    assert USER_ENTITY.singleton_alias is not None
    alias_segment, _ = USER_ENTITY.singleton_alias
    assert alias_segment == "me"


# --- Extras binding ------------------------------------------------------


def test_detail_extras_path_points_at_user_detail_extras():
    """The dotted path is the security-visible binding: the projection
    that strips private fields lives in `user_detail_extras`. Pinning
    the string here means a rename of the callable can't silently
    de-project the response."""
    assert (
        USER_ENTITY.detail_extras_path
        == "src.logic.users.user_processing.user_detail_extras"
    )
