"""Audit-log helper for mutation handlers.

Wraps `AuditRepository.record(...)` with the calling convention used by the
handlers in `src/logic/`. Handlers call this once per mutation, **inside the
same transaction** as the mutation itself — the discipline in
`RESOURCE_GRAMMAR.md:135` requires the audit row to be durable iff the
mutation is. The handler still owns the commit.

`actor_id` is `None` for unauthenticated mutations (e.g. self-signup); the
schema permits it.

`AuditAction` is the closed vocabulary of mutation kinds. Add a member here
when wiring `record_audit` into a new mutation handler; never reuse an
existing value for a different semantic — values are persisted forever and
existing rows depend on the meaning being stable.
"""

import logging
from enum import Enum
from typing import Any
from uuid import UUID

from src.models import AuditLog
from src.repositories.audit_repository import AuditRepository

logger = logging.getLogger(__name__)


class AuditAction(str, Enum):
    """Closed vocabulary of mutation actions recorded in the audit log.

    Inherits from `str` so values serialize transparently into the
    `audit_log.action` column and equality comparisons against raw strings
    keep working (`AuditAction.CREATE_POST == "create_post"` is True).
    """

    CREATE_POST = "create_post"
    UPDATE_POST = "update_post"
    DELETE_POST = "delete_post"
    SET_USER_ACTIVATION = "set_user_activation"
    DELETE_USER = "delete_user"
    REGISTER = "register"


async def record_audit(
    audit_repo: AuditRepository,
    *,
    actor_id: UUID | None,
    resource_type: str,
    resource_id: UUID,
    action: AuditAction,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    """Record a single audit row. Returns the persisted row (flushed, not committed)."""
    row = await audit_repo.record(
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        before=before,
        after=after,
    )
    logger.info(f"Audit: actor={actor_id} {action.value} {resource_type}/{resource_id}")
    return row
