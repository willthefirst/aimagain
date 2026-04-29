"""Audit-log helper for mutation handlers.

Wraps `AuditRepository.record(...)` with the calling convention used by the
handlers in `src/logic/`. Handlers call this once per mutation, **inside the
same transaction** as the mutation itself — the discipline in
`RESOURCE_GRAMMAR.md:135` requires the audit row to be durable iff the
mutation is. The handler still owns the commit.

`actor_id` is `None` for unauthenticated mutations (e.g. self-signup); the
schema permits it.
"""

import logging
from typing import Any
from uuid import UUID

from src.models import AuditLog
from src.repositories.audit_repository import AuditRepository

logger = logging.getLogger(__name__)


async def record_audit(
    audit_repo: AuditRepository,
    *,
    actor_id: UUID | None,
    resource_type: str,
    resource_id: UUID,
    action: str,
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
    logger.info(f"Audit: actor={actor_id} {action} {resource_type}/{resource_id}")
    return row
