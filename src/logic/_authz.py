"""Authorization helpers shared across logic-layer handlers.

The leading-underscore filename matches `src/schemas/_validators.py` —
shared infra at the layer's parent level, importable from every cluster.

The boolean predicates (`is_admin`, `is_owner`, `is_owner_or_admin`)
are the source of truth for the authorization rules. The asserting
form (`assert_owner_or_admin`) wraps `is_owner_or_admin` for use as a
single-callable in `EntitySpec.write_authz` (the raising form, consumed
by mutation handlers); the predicate is bound directly to
`EntitySpec.can_write` for use in template-context flags
(`can_edit = entity.can_write(target, user)`) so detail handlers don't
re-derive the composition.

The two forms always pair, so specs declare them together via
`EntitySpec.auth_policy=OWNER_OR_ADMIN` — the sentinel lives next to
`AuthzPolicy` in `src/api/common/entity_spec.py` (importing the
callables defined here) so the spec-side dataclass and its canonical
instance stay co-located without forcing a circular import.
"""

from src.api.common.exceptions import ForbiddenError
from src.models import User


def is_admin(user: User | None) -> bool:
    """True iff `user` is authenticated and is a superuser."""
    return user is not None and user.is_superuser


def is_owner(obj, user: User | None, *, owner_attr: str = "owner_id") -> bool:
    """True iff `user` is authenticated and `obj`'s owner-FK matches.

    `owner_attr` names the foreign-key column on `obj` that points at
    the owning user. Defaults to `"owner_id"`, which matches both
    `Post.owner_id` and `Provider.owner_id`; the knob is kept for future
    entities whose owner FK is not literally named `owner_id`.
    """
    if user is None:
        return False
    return getattr(obj, owner_attr) == user.id


def is_owner_or_admin(obj, user: User | None, *, owner_attr: str = "owner_id") -> bool:
    """True iff `user` owns `obj` (by FK) or is a superuser.

    Predicate form of `assert_owner_or_admin`. The two forms share one
    composition — `assert_owner_or_admin` delegates here — so a future
    rule change happens in exactly one place. Bound to
    `EntitySpec.can_write` for entities whose write rule is owner-or-admin
    (posts, providers, provider credentials).
    """
    return is_owner(obj, user, owner_attr=owner_attr) or is_admin(user)


def is_self_or_admin(actor: User | None, target) -> bool:
    """True iff `actor` is authenticated and is either `target` itself or a superuser.

    Distinct signature from `is_owner`: the resource *is* the user, not
    an FK to one, so there is no `owner_attr` knob — equality is between
    `actor.id` and `target.id` directly.
    """
    if actor is None:
        return False
    return actor.id == target.id or actor.is_superuser


def forbid_self_action(target, actor: User, *, detail: str) -> None:
    """Raise `ForbiddenError` if `actor` is operating on themselves.

    For admin-only mutations whose target is a `User` row, the route's
    `current_admin_user` dep already blocks non-admins — but an admin
    could still aim the verb at their own account. The product rule is
    that admins cannot self-mutate via these endpoints; this helper is
    the single place that rule is expressed. `detail` is the full
    error message so each call can phrase the action naturally
    (activation, deletion, …).
    """
    if target.id == actor.id:
        raise ForbiddenError(detail=detail)


def assert_owner_or_admin(
    obj,
    user: User,
    *,
    owner_attr: str = "owner_id",
    action: str = "edit this resource",
) -> None:
    """Raise `ForbiddenError` unless `user` owns `obj` or is a superuser.

    Asserting wrapper over `is_owner_or_admin` — the predicate is the
    rule, this function is the raising form for `EntitySpec.write_authz`.
    `action` is interpolated into the error message: ``"Only the owner
    or an admin can {action}"``.
    """
    if not is_owner_or_admin(obj, user, owner_attr=owner_attr):
        raise ForbiddenError(detail=f"Only the owner or an admin can {action}")
