"""Append-only data access for the audit log per `RESOURCE_GRAMMAR.md:135`.

Deliberately exposes only writes and read-by-id — there is no `update_*` or
`delete_*`. Audit rows are immutable; the discipline relies on it.
"""

from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import AuditLog

from .base import BaseRepository


class AuditRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

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
        audit `at` field — see `src/models/audit_log.py`.
        """
        row = AuditLog(
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            before=before,
            after=after,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def get_by_id(self, audit_id: UUID) -> AuditLog | None:
        """Look up a single audit row. Primarily for tests."""
        stmt = select(AuditLog).filter(AuditLog.id == audit_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_for_resource(
        self, *, resource_type: str, resource_id: UUID
    ) -> Sequence[AuditLog]:
        """List audit rows for a given resource, oldest first."""
        stmt = (
            select(AuditLog)
            .filter(
                AuditLog.resource_type == resource_type,
                AuditLog.resource_id == resource_id,
            )
            .order_by(AuditLog.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
