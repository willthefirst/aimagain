from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select

from src.domain.models import Verification
from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import register_repository


class VerificationRepository(BaseRepository):
    """Append-only persistence for `Verification` rows. The orchestrator
    is the only writer; callers compose `record_for_*(...)` with
    `record_audit_for(...)` in the same transaction.

    Verification rows are polymorphic: each row carries a `subject_type`
    discriminator + exactly one of (`clinician_id`, `org_id`). The
    `record_for_clinician` / `record_for_org` split keeps callers from
    having to remember which fields belong to which side; the CHECK
    constraint on the row enforces the invariant.
    """

    async def record_for_clinician(
        self,
        *,
        clinician_id: UUID,
        status: str,
        flags: list[str],
        nppes_result: dict[str, Any] | None,
        oig_match: bool,
        name_match_score: float | None,
        event_type: str = "npi_resolved",
        evidence: dict[str, Any] | None = None,
    ) -> Verification:
        return await self._persist_new(
            Verification(
                subject_type="clinician",
                clinician_id=clinician_id,
                event_type=event_type,
                status=status,
                flags=flags,
                nppes_result=nppes_result,
                evidence=evidence,
                oig_match=oig_match,
                name_match_score=name_match_score,
            )
        )

    async def record_for_org(
        self,
        *,
        org_id: UUID,
        status: str,
        flags: list[str],
        nppes_result: dict[str, Any] | None,
        name_match_score: float | None,
        event_type: str = "npi_resolved",
        evidence: dict[str, Any] | None = None,
    ) -> Verification:
        return await self._persist_new(
            Verification(
                subject_type="organization",
                org_id=org_id,
                event_type=event_type,
                status=status,
                flags=flags,
                nppes_result=nppes_result,
                evidence=evidence,
                oig_match=False,
                name_match_score=name_match_score,
            )
        )

    # `record(...)` is kept as a thin alias for the old clinician-only
    # signature so the existing orchestrator + tests keep working without
    # threading the discriminator through every call site.
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
        return await self.record_for_clinician(
            clinician_id=clinician_id,
            status=status,
            flags=flags,
            nppes_result=nppes_result,
            oig_match=oig_match,
            name_match_score=name_match_score,
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

    async def latest_for_org(self, org_id: UUID) -> Verification | None:
        stmt = (
            select(Verification)
            .filter(Verification.org_id == org_id)
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

    async def list_for_org(
        self,
        org_id: UUID,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> Sequence[Verification]:
        stmt = (
            select(Verification)
            .filter(Verification.org_id == org_id)
            .order_by(Verification.created_at.desc())
        )
        return await self._list(stmt, offset=offset, limit=limit)


get_verification_repository = register_repository(VerificationRepository)
