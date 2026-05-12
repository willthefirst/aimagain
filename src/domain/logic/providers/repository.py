from typing import Sequence
from uuid import UUID

from sqlalchemy import select

from src.domain.models import Provider, ProviderLicensure
from src.framework.base_repository import BaseRepository


class ProviderRepository(BaseRepository):
    # --- Provider reads --------------------------------------------

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
    # The framework's `handle_create` calls `repo.create(Provider(...))`
    # (the public alias on `BaseRepository`) directly — no `create_provider`
    # wrapper needed. Inline credential rows append via `repo.add_child`.
