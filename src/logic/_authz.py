"""Authorization helpers shared across logic-layer handlers.

The leading-underscore filename matches `src/schemas/_validators.py` —
shared infra at the layer's parent level, importable from every cluster.
"""

from src.api.common.exceptions import ForbiddenError
from src.models import User


def assert_owner_or_admin(
    obj,
    user: User,
    *,
    owner_attr: str = "owner_id",
    action: str = "edit this resource",
) -> None:
    """Raise `ForbiddenError` unless `user` owns `obj` or is a superuser.

    `owner_attr` names the foreign-key column on `obj` that points at the
    owning user (`Post.owner_id` vs `Provider.user_id`). `action` is
    interpolated into the error message: ``"Only the owner or an admin
    can {action}"``.
    """
    owner_id = getattr(obj, owner_attr)
    if owner_id != user.id and not user.is_superuser:
        raise ForbiddenError(detail=f"Only the owner or an admin can {action}")
