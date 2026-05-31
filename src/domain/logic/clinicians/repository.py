from typing import Sequence
from uuid import UUID

from sqlalchemy import select

from src.domain.models import Clinician, ClinicianLicensure
from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import register_repository


class ClinicianRepository(BaseRepository):
    async def get_by_user_id(self, user_id: UUID) -> Clinician | None:
        stmt = select(Clinician).filter(Clinician.owner_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> Sequence[Clinician]:
        return await self.list_owned_by(Clinician, user_id, offset=offset, limit=limit)

    async def list_for_verification(self) -> Sequence[Clinician]:
        return await self._list(
            select(Clinician).filter(Clinician.deleted_at.is_(None))
        )

    async def list_pending_npi(self) -> Sequence[Clinician]:
        """Clinicians with `npi_match_status == 'pending'` — the work
        queue for the NPI worker job. Picks up rows after an end-user
        submission (`POST /clinicians/{id}/npi`) and any admin-driven
        re-submit. Excludes soft-deleted rows."""
        return await self._list(
            select(Clinician).filter(
                Clinician.npi_match_status == "pending",
                Clinician.deleted_at.is_(None),
            )
        )

    async def list_clinicians(
        self,
        *,
        license_type: list[str] | None = None,
        issuing_state: list[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> Sequence[Clinician]:
        """List directory entries newest first. Both filters are multi-select;
        when set, joins through `clinician_licensures` (SQL table) and distincts so a
        clinician with multiple matching licensures appears once."""
        stmt = select(Clinician)
        if license_type or issuing_state:
            stmt = stmt.join(
                ClinicianLicensure,
                ClinicianLicensure.clinician_id == Clinician.id,
            )
            if license_type:
                stmt = stmt.filter(ClinicianLicensure.license_type.in_(license_type))
            if issuing_state:
                stmt = stmt.filter(ClinicianLicensure.issuing_state.in_(issuing_state))
            stmt = stmt.distinct()
        stmt = stmt.order_by(Clinician.created_at.desc())
        return await self._list(stmt, offset=offset, limit=limit)


get_clinician_repository = register_repository(ClinicianRepository)
