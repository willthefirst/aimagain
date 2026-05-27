from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select

from src.domain.models import Verification
from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import register_repository


class VerificationRepository(BaseRepository):
    """Append-only persistence for `Verification` rows. The orchestrator
    is the only writer; callers compose `record(...)` with
    `record_audit_for(...)` in the same transaction."""

    async def record(
        self,
        *,
        clinician_id: UUID,
        status: str,
        flags: list[str],
        nppes_result: dict[str, Any] | None,
        oig_match: bool,
        name_match_score: float | None,
    ) -> Verification:
        return await self._persist_new(
            Verification(
                clinician_id=clinician_id,
                status=status,
                flags=flags,
                nppes_result=nppes_result,
                oig_match=oig_match,
                name_match_score=name_match_score,
            )
        )

    async def latest_for_clinician(self, clinician_id: UUID) -> Verification | None:
        stmt = (
            select(Verification)
            .filter(Verification.clinician_id == clinician_id)
            .order_by(Verification.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_for_clinician(
        self,
        clinician_id: UUID,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> Sequence[Verification]:
        stmt = (
            select(Verification)
            .filter(Verification.clinician_id == clinician_id)
            .order_by(Verification.created_at.desc())
        )
        return await self._list(stmt, offset=offset, limit=limit)


get_verification_repository = register_repository(VerificationRepository)
