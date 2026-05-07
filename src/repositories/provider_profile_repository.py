from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    ProviderCertification,
    ProviderEducation,
    ProviderLicensure,
    ProviderProfile,
)

from .base import BaseRepository


class ProviderProfileRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    # --- ProviderProfile reads --------------------------------------------

    async def get_by_id(self, profile_id: UUID) -> ProviderProfile | None:
        """Retrieves a profile by id. Sub-table relationships are
        eager-loaded via `lazy="selectin"` on the model."""
        return await self._get_by_id(ProviderProfile, profile_id)

    async def get_by_user_id(self, user_id: UUID) -> ProviderProfile | None:
        """Retrieves a profile by its owning user id. The
        `uq_provider_profiles_user_id` constraint guarantees at most one."""
        stmt = select(ProviderProfile).filter(ProviderProfile.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_profiles(
        self,
        *,
        license_type: str | None = None,
        issuing_state: str | None = None,
    ) -> Sequence[ProviderProfile]:
        """Lists profiles, newest first. When a filter is set, joins
        through `provider_licensures` and `.distinct()`s the parents so
        a profile with multiple matching licensures appears once."""
        stmt = select(ProviderProfile)
        if license_type is not None or issuing_state is not None:
            stmt = stmt.join(
                ProviderLicensure,
                ProviderLicensure.profile_id == ProviderProfile.id,
            )
            if license_type is not None:
                stmt = stmt.filter(ProviderLicensure.license_type == license_type)
            if issuing_state is not None:
                stmt = stmt.filter(ProviderLicensure.issuing_state == issuing_state)
            stmt = stmt.distinct()
        stmt = stmt.order_by(ProviderProfile.created_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    # --- ProviderProfile mutations ----------------------------------------

    async def create_profile(self, user_id: UUID, **fields: Any) -> ProviderProfile:
        return await self._persist_new(ProviderProfile(user_id=user_id, **fields))

    async def update_profile(
        self, profile: ProviderProfile, **fields: Any
    ) -> ProviderProfile:
        return await self._patch(profile, **fields)

    async def delete_profile(self, profile: ProviderProfile) -> None:
        await self._delete(profile)

    # --- Licensure sub-table ----------------------------------------------

    async def get_licensure_by_id(self, licensure_id: UUID) -> ProviderLicensure | None:
        return await self._get_by_id(ProviderLicensure, licensure_id)

    async def add_licensure(
        self, profile: ProviderProfile, **fields: Any
    ) -> ProviderLicensure:
        return await self._add_child(profile, "licensures", ProviderLicensure(**fields))

    async def update_licensure(
        self, licensure: ProviderLicensure, **fields: Any
    ) -> ProviderLicensure:
        return await self._patch(licensure, **fields)

    async def delete_licensure(self, licensure: ProviderLicensure) -> None:
        await self._delete(licensure)

    # --- Education sub-table ----------------------------------------------

    async def get_education_by_id(self, education_id: UUID) -> ProviderEducation | None:
        return await self._get_by_id(ProviderEducation, education_id)

    async def add_education(
        self, profile: ProviderProfile, **fields: Any
    ) -> ProviderEducation:
        return await self._add_child(profile, "educations", ProviderEducation(**fields))

    async def update_education(
        self, education: ProviderEducation, **fields: Any
    ) -> ProviderEducation:
        return await self._patch(education, **fields)

    async def delete_education(self, education: ProviderEducation) -> None:
        await self._delete(education)

    # --- Certification sub-table ------------------------------------------

    async def get_certification_by_id(
        self, certification_id: UUID
    ) -> ProviderCertification | None:
        return await self._get_by_id(ProviderCertification, certification_id)

    async def add_certification(
        self, profile: ProviderProfile, **fields: Any
    ) -> ProviderCertification:
        return await self._add_child(
            profile, "certifications", ProviderCertification(**fields)
        )

    async def update_certification(
        self, cert: ProviderCertification, **fields: Any
    ) -> ProviderCertification:
        return await self._patch(cert, **fields)

    async def delete_certification(self, cert: ProviderCertification) -> None:
        await self._delete(cert)
