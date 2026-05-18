"""Append-only data access for the audit log per `RESOURCE_GRAMMAR.md:135`.

Deliberately exposes only writes and read-by-id — there is no `update_*` or
`delete_*`. Audit rows are immutable; the discipline relies on it.
"""

from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select

from src.framework.audit.log import AuditLog
from src.framework.persistence.base_repository import BaseRepository


class AuditRepository(BaseRepository):
    async def record(
        self,
        *,
        actor_id: UUID | None,
        resource_type: str,
        resource_id: UUID,
        action: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Persist a new audit row and flush; the caller commits.

        The row's `created_at` (inherited from BaseModel) doubles as the
        audit `at` field — see `src/domain/models/audit_log.py`.
        """
        return await self._persist_new(
            AuditLog(
                actor_id=actor_id,
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                before=before,
                after=after,
            )
        )

    async def list_for_resource(
        self, *, resource_type: str, resource_id: UUID
    ) -> Sequence[AuditLog]:
        """List audit rows for a given resource, oldest first."""
        return await self._list(
            select(AuditLog)
            .filter(
                AuditLog.resource_type == resource_type,
                AuditLog.resource_id == resource_id,
            )
            .order_by(AuditLog.created_at.asc())
        )
