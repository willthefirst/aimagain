from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select

from src.domain.models import Verification
from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import register_repository


class VerificationRepository(BaseRepository):
    """Append-only persistence for `Verification` rows. The orchestrator
    in `handlers.py` (#528 / A4) is the only writer; callers compose a
    `record(...)` with a `record_audit_for(...)` in the same transaction
    (no `mutate()` here — there is no pre-existing target to snapshot on
    create). The read methods drive the admin UI's verification history
    panel."""

    async def record(
        self,
        *,
        provider_id: UUID,
        status: str,
        flags: list[str],
        nppes_result: dict[str, Any] | None,
        oig_match: bool,
        name_match_score: float | None,
    ) -> Verification:
        """Persist a new verification attempt for `provider_id`. Caller
        owns the transaction boundary (the audit row is written next, then
        a single `session.commit()`)."""
        return await self._persist_new(
            Verification(
                provider_id=provider_id,
                status=status,
                flags=flags,
                nppes_result=nppes_result,
                oig_match=oig_match,
                name_match_score=name_match_score,
            )
        )

    async def latest_for_provider(self, provider_id: UUID) -> Verification | None:
        """Return the most recent `Verification` row for the given
        provider, or `None` if none exist. Drives the per-provider
        verification badge on the admin UI — that surface only ever
        looks at the latest attempt."""
        stmt = (
            select(Verification)
            .filter(Verification.provider_id == provider_id)
            .order_by(Verification.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_for_provider(
        self,
        provider_id: UUID,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> Sequence[Verification]:
        """Return verification history for the given provider, newest
        first. Drives the per-provider history panel on the admin UI."""
        stmt = (
            select(Verification)
            .filter(Verification.provider_id == provider_id)
            .order_by(Verification.created_at.desc())
        )
        return await self._list(stmt, offset=offset, limit=limit)


get_verification_repository = register_repository(VerificationRepository)
