# src/logic/auth_processing.py
import logging

from fastapi import Depends, Request
from fastapi_users import models
from fastapi_users.manager import BaseUserManager, UserManagerDependency

from src.auth_config import get_user_manager
from src.domain.users.schema import UserAuditSnapshot, UserCreate, UserRead
from src.framework.audit import AuditAction, make_snapshotter, record_audit
from src.framework.audit_repository import AuditRepository
from src.framework.dependencies import get_audit_repository

logger = logging.getLogger(__name__)

AppUserManager = UserManagerDependency[models.UP, models.ID]

_snapshot_user = make_snapshotter(UserAuditSnapshot)


async def handle_registration(
    request_data: UserCreate,
    request: Request,
    user_manager: BaseUserManager[models.UP, models.ID] = Depends(get_user_manager),
    audit_repo: AuditRepository = Depends(get_audit_repository),
) -> UserRead:
    """Register a new user, then write an audit row.

    Best-effort atomicity. `fastapi_users`' `user_manager.create` commits
    internally via `SQLAlchemyUserDatabase.create`, so the audit insert
    that follows is a separate transaction on the same session. If the
    audit insert fails after the user is committed, we have a user without
    a matching audit row — surfaced in logs and as a 500 to the caller,
    but not rolled back. Authenticated mutation handlers (post create/edit,
    user activation/delete) get true atomicity via shared transactions; this
    is the one exception.
    """
    created_user = await user_manager.create(request_data, safe=True, request=request)
    await record_audit(
        audit_repo,
        actor_id=None,  # self-signup has no authenticated actor
        resource_type="user",
        resource_id=created_user.id,
        action=AuditAction.REGISTER,
        before=None,
        after=_snapshot_user(created_user),
    )
    await audit_repo.session.commit()
    return created_user
