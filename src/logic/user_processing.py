import logging
from uuid import UUID

from fastapi import Request

from src.api.common.exceptions import ForbiddenError, NotFoundError
from src.logic.audit import AuditAction, record_audit
from src.models import User
from src.repositories.audit_repository import AuditRepository
from src.repositories.user_repository import UserRepository
from src.schemas.user import UserActivationUpdate

logger = logging.getLogger(__name__)


def _snapshot_user_activation(user: User) -> dict:
    """Capture just the activation axis for audit before/after."""
    return {"is_active": user.is_active}


def _snapshot_user(user: User) -> dict:
    """Capture user-meaningful fields for `delete_user` audit `before`."""
    return {
        "username": user.username,
        "email": user.email,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
    }


async def handle_list_users(
    request: Request,
    user_repo: UserRepository,
    requesting_user: User,
):
    """
    Handles the core logic for listing users.

    Args:
        request: The FastAPI request object.
        user_repo: The user repository dependency.
        requesting_user: The currently authenticated user.

    Returns:
        A dictionary containing the context for the template.

    Raises:
        Exception: Propagates exceptions from the repository layer.
    """
    logger.debug(f"Handler: Listing users for user {requesting_user.id}.")

    try:
        users_list = await user_repo.list_users(
            exclude_user=requesting_user,
        )
    except Exception as e:
        logger.error(
            f"Handler: Error listing users from repository: {e}", exc_info=True
        )
        raise

    logger.debug(
        f"Handler: Successfully retrieved {len(users_list)} users for user {requesting_user.id}."
    )

    return {"request": request, "users": users_list, "current_user": requesting_user}


async def handle_get_user_detail(
    request: Request,
    user_id: UUID,
    user_repo: UserRepository,
    requesting_user: User,
):
    """Loads a single user for the detail page; 404s if missing."""
    target = await user_repo.get_user_by_id(user_id)
    if target is None:
        raise NotFoundError(detail="User not found")

    return {
        "request": request,
        "target_user": target,
        "current_user": requesting_user,
    }


async def handle_set_user_activation(
    user_id: UUID,
    payload: UserActivationUpdate,
    user_repo: UserRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> User:
    """Admin-only: set a user's activation state. Writes an audit row in the
    same transaction.

    Self-guard lives here so direct API calls can't bypass the template's
    `{% if %}` hide. The route's `current_admin_user` dep blocks non-admins.
    """
    target = await user_repo.get_user_by_id(user_id)
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
    updated = await user_repo.set_user_activation(target, is_active=is_active)
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type="user",
        resource_id=updated.id,
        action=AuditAction.SET_USER_ACTIVATION,
        before=before,
        after=_snapshot_user_activation(updated),
    )
    await user_repo.session.commit()
    return updated


async def handle_delete_user(
    user_id: UUID,
    user_repo: UserRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> None:
    """Admin-only: hard-delete a user row. Writes an audit row in the same
    transaction (recorded before the delete fires so the actor FK is still
    valid; the row's `before` captures the soon-to-be-gone state).

    Self-guard mirrors `handle_set_user_activation`; the route dep blocks non-admins.
    """
    target = await user_repo.get_user_by_id(user_id)
    if target is None:
        raise NotFoundError(detail="User not found")
    if target.id == requesting_user.id:
        raise ForbiddenError(detail="Admins cannot delete their own account here")

    logger.info(f"Handler: admin {requesting_user.id} hard-deleting user {target.id}")
    before = _snapshot_user(target)
    target_id = target.id
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type="user",
        resource_id=target_id,
        action=AuditAction.DELETE_USER,
        before=before,
        after=None,
    )
    await user_repo.delete_user(target)
    await user_repo.session.commit()
