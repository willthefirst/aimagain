"""Authorization helpers shared across logic-layer handlers.

The leading-underscore filename matches `src/schemas/_validators.py` —
shared infra at the layer's parent level, importable from every cluster.

The boolean predicates (`is_admin`, `is_owner`) are the source of truth
for the authorization rules. Handlers compose them to compute
template-context flags (`can_edit = is_owner(post, user) or is_admin(user)`),
and the asserting form (`assert_owner_or_admin`) wraps the same
composition for use as a single-callable in `ResourceSpec.write_authz`.
"""

from src.api.common.exceptions import ForbiddenError
from src.models import User


def is_admin(user: User | None) -> bool:
    """True iff `user` is authenticated and is a superuser."""
    return user is not None and user.is_superuser


def is_owner(obj, user: User | None, *, owner_attr: str = "owner_id") -> bool:
    """True iff `user` is authenticated and `obj`'s owner-FK matches.

    `owner_attr` names the foreign-key column on `obj` that points at
    the owning user (`Post.owner_id` vs `Provider.user_id`).
    """
    if user is None:
        return False
    return getattr(obj, owner_attr) == user.id


def is_self_or_admin(actor: User | None, target) -> bool:
    """True iff `actor` is authenticated and is either `target` itself or a superuser.

    Distinct signature from `is_owner`: the resource *is* the user, not
    an FK to one, so there is no `owner_attr` knob — equality is between
    `actor.id` and `target.id` directly.
    """
    if actor is None:
        return False
    return actor.id == target.id or actor.is_superuser


def assert_owner_or_admin(
    obj,
    user: User,
    *,
    owner_attr: str = "owner_id",
    action: str = "edit this resource",
) -> None:
    """Raise `ForbiddenError` unless `user` owns `obj` or is a superuser.

    `action` is interpolated into the error message: ``"Only the owner
    or an admin can {action}"``.
    """
    if not (is_owner(obj, user, owner_attr=owner_attr) or is_admin(user)):
        raise ForbiddenError(detail=f"Only the owner or an admin can {action}")
