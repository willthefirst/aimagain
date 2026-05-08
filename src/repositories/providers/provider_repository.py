from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Provider,
    ProviderCertification,
    ProviderEducation,
    ProviderLicensure,
)

from ..base import BaseRepository


class ProviderRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    # --- Provider reads --------------------------------------------

    async def get_by_id(self, provider_id: UUID) -> Provider | None:
        """Retrieves a profile by id. Sub-table relationships are
        eager-loaded via `lazy="selectin"` on the model."""
        return await self._get_by_id(Provider, provider_id)

    async def get_by_user_id(self, user_id: UUID) -> Provider | None:
        """Retrieves a profile owned by the given user. A user may own
        multiple profiles; this returns whichever the DB hands back first
        with no defined ordering, so callers needing a single canonical
        profile should not rely on this method.
        """
        stmt = select(Provider).filter(Provider.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_for_user(self, user_id: UUID) -> Sequence[Provider]:
        """Lists every profile owned by the given user, newest first."""
        stmt = (
            select(Provider)
            .filter(Provider.user_id == user_id)
            .order_by(Provider.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_providers(
        self,
        *,
        license_type: str | None = None,
        issuing_state: str | None = None,
    ) -> Sequence[Provider]:
        """Lists profiles, newest first. When a filter is set, joins
        through `provider_licensures` and `.distinct()`s the parents so
        a profile with multiple matching licensures appears once."""
        stmt = select(Provider)
        if license_type is not None or issuing_state is not None:
            stmt = stmt.join(
                ProviderLicensure,
                ProviderLicensure.provider_id == Provider.id,
            )
            if license_type is not None:
                stmt = stmt.filter(ProviderLicensure.license_type == license_type)
            if issuing_state is not None:
                stmt = stmt.filter(ProviderLicensure.issuing_state == issuing_state)
            stmt = stmt.distinct()
        stmt = stmt.order_by(Provider.created_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    # --- Provider mutations ----------------------------------------

    async def create_provider(self, user_id: UUID, **fields: Any) -> Provider:
        return await self._persist_new(Provider(user_id=user_id, **fields))

    async def update_provider(self, profile: Provider, **fields: Any) -> Provider:
        return await self._patch(profile, **fields)

    async def delete_provider(self, profile: Provider) -> None:
        await self._delete(profile)

    # --- Licensure sub-table ----------------------------------------------

    async def get_licensure_by_id(self, licensure_id: UUID) -> ProviderLicensure | None:
        return await self._get_by_id(ProviderLicensure, licensure_id)

    async def add_licensure(
        self, profile: Provider, **fields: Any
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
        self, profile: Provider, **fields: Any
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
        self, profile: Provider, **fields: Any
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
