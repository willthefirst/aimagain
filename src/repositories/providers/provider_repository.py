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
        """Retrieves a provider by id. Sub-table relationships are
        eager-loaded via `lazy="selectin"` on the model."""
        return await self._get_by_id(Provider, provider_id)

    async def get_by_user_id(self, user_id: UUID) -> Provider | None:
        """Retrieves a provider owned by the given user. A user may own
        multiple providers; this returns whichever the DB hands back first
        with no defined ordering, so callers needing a single canonical
        provider should not rely on this method.
        """
        stmt = select(Provider).filter(Provider.owner_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_for_user(self, user_id: UUID) -> Sequence[Provider]:
        """Lists every provider owned by the given user, newest first."""
        return await self._list(
            select(Provider)
            .filter(Provider.owner_id == user_id)
            .order_by(Provider.created_at.desc())
        )

    async def list_providers(
        self,
        *,
        license_type: str | None = None,
        issuing_state: str | None = None,
    ) -> Sequence[Provider]:
        """Lists providers, newest first. When a filter is set, joins
        through `provider_licensures` and `.distinct()`s the parents so
        a provider with multiple matching licensures appears once."""
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
        return await self._list(stmt)

    # --- Provider mutations ----------------------------------------

    async def create_provider(self, user_id: UUID, **fields: Any) -> Provider:
        return await self._persist_new(Provider(owner_id=user_id, **fields))

    # --- Licensure sub-table ----------------------------------------------

    async def add_licensure(
        self, provider: Provider, **fields: Any
    ) -> ProviderLicensure:
        return await self._add_child(
            provider, "licensures", ProviderLicensure(**fields)
        )

    # --- Education sub-table ----------------------------------------------

    async def add_education(
        self, provider: Provider, **fields: Any
    ) -> ProviderEducation:
        return await self._add_child(
            provider, "educations", ProviderEducation(**fields)
        )

    # --- Certification sub-table ------------------------------------------

    async def add_certification(
        self, provider: Provider, **fields: Any
    ) -> ProviderCertification:
        return await self._add_child(
            provider, "certifications", ProviderCertification(**fields)
        )
