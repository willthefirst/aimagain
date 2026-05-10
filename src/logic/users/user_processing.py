import logging
from uuid import UUID

from fastapi import Request

from src.api.common.exceptions import ForbiddenError, NotFoundError
from src.api.common.projections import project_view
from src.api.common.specs.user import USER_ENTITY
from src.logic._authz import is_admin
from src.logic.audit import make_snapshotter, mutate, record_audit
from src.models import User
from src.repositories.audit_repository import AuditRepository
from src.repositories.providers.provider_repository import ProviderRepository
from src.repositories.users.user_repository import UserRepository
from src.schemas.users.user import (
    UserActivationAuditSnapshot,
    UserActivationUpdate,
)

logger = logging.getLogger(__name__)

_snapshot_user_activation = make_snapshotter(UserActivationAuditSnapshot)


async def handle_list_users(
    request: Request,
    repo: UserRepository,
    requesting_user: User,
):
    """
    Handles the core logic for listing users.

    Args:
        request: The FastAPI request object.
        repo: The user repository dependency.
        requesting_user: The currently authenticated user.

    Returns:
        A dictionary containing the context for the template.

    Raises:
        Exception: Propagates exceptions from the repository layer.
    """
    users_list = await repo.list_users(exclude_user=requesting_user)

    # `list_users` excludes the viewer, so every row is some other user;
    # admin-actions visibility reduces to a single flag for the whole
    # list rather than a per-row computation.
    return {
        "request": request,
        "users": users_list,
        "current_user": requesting_user,
        "can_admin_actions": is_admin(requesting_user),
    }


async def handle_get_user_detail(
    request: Request,
    user_id: UUID,
    repo: UserRepository,
    provider_repo: ProviderRepository,
    requesting_user: User,
):
    """Loads a single user for the detail page along with the providers
    they own; 404s if the user is missing. Provider data is already
    publicly available via `GET /providers`, so the embedded list is gated
    only by the existing user-detail auth (any active user)."""
    target = await repo.get_user_by_id(user_id)
    if target is None:
        raise NotFoundError(detail="User not found")

    providers = await provider_repo.list_for_user(user_id)

    # Admin actions never apply to the viewer's own profile, so the
    # self-guard composes with the admin check at flag-computation time;
    # the partial just checks the flag.
    is_self = requesting_user is not None and target.id == requesting_user.id
    can_admin_actions = is_admin(requesting_user) and not is_self
    can_view_private = USER_ENTITY.private_field_predicate(requesting_user, target)

    # Project target_user into a dict that omits private fields for
    # viewers outside the predicate. Defense in depth: a forgotten
    # template guard can re-leak; a missing dict key can't.
    target_view = project_view(
        target,
        public_fields=("id", "username"),
        actor=requesting_user,
        private_fields=USER_ENTITY.private_fields,
        private_field_predicate=USER_ENTITY.private_field_predicate,
    )

    return {
        "request": request,
        "target_user": target_view,
        "providers": providers,
        "current_user": requesting_user,
        "can_admin_actions": can_admin_actions,
        "can_view_private": can_view_private,
    }


async def handle_set_user_activation(
    user_id: UUID,
    payload: UserActivationUpdate,
    repo: UserRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> User:
    """Admin-only: set a user's activation state. Writes an audit row in the
    same transaction.

    Self-guard lives here so direct API calls can't bypass the template's
    `{% if %}` hide. The route's `current_admin_user` dep blocks non-admins.
    """
    target = await repo.get_user_by_id(user_id)
    if target is None:
        raise NotFoundError(detail="User not found")
    if target.id == requesting_user.id:
        raise ForbiddenError(
            detail="Admins cannot change their own activation state here"
        )

    is_active = payload.state == "active"
    logger.info(
        f"Handler: admin {requesting_user.id} setting activation={payload.state} on user {target.id}"
    )
    before = _snapshot_user_activation(target)
    updated = await repo.set_user_activation(target, is_active=is_active)
    activation_axis = USER_ENTITY.state_axis("activation")
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type=USER_ENTITY.audit.type,
        resource_id=updated.id,
        action=activation_axis.action,
        before=before,
        after=_snapshot_user_activation(updated),
    )
    await repo.session.commit()
    return updated


async def handle_delete_user(
    user_id: UUID,
    repo: UserRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> None:
    """Admin-only: hard-delete a user row. Writes an audit row in the same
    transaction; `before` captures the soon-to-be-gone state, `after` is None.

    Self-delete is forbidden (the actor is never the target), so writing the
    audit row after the delete fires is safe — the actor row stays around
    for the FK and `mutate()` captures `target.id` up front.
    """
    target = await repo.get_user_by_id(user_id)
    if target is None:
        raise NotFoundError(detail="User not found")
    if target.id == requesting_user.id:
        raise ForbiddenError(detail="Admins cannot delete their own account here")

    logger.info(f"Handler: admin {requesting_user.id} hard-deleting user {target.id}")
    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=target,
        resource=USER_ENTITY.audit,
        verb="delete",
    ):
        await repo.delete_user(target)
