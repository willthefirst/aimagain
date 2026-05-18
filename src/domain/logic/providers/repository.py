from typing import Sequence
from uuid import UUID

from sqlalchemy import select

from src.domain.models import Provider, ProviderLicensure
from src.framework.persistence.base_repository import BaseRepository


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

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> Sequence[Provider]:
        """Lists every provider owned by the given user, newest first.
        `offset`/`limit` come from the pagination layer (the bespoke
        `handle_list_user_providers` handler computes them)."""
        return await self._list(
            select(Provider)
            .filter(Provider.owner_id == user_id)
            .order_by(Provider.created_at.desc()),
            offset=offset,
            limit=limit,
        )

    async def list_providers(
        self,
        *,
        license_type: list[str] | None = None,
        issuing_state: list[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> Sequence[Provider]:
        """Lists providers, newest first. Both filters are multi-select
        lists; each non-empty list ANDs into the join (any-of within
        the list, all-of across filters). When either filter is set,
        joins through `provider_licensures` and `.distinct()`s the
        parents so a provider with multiple matching licensures
        appears once. `offset`/`limit` come from the framework's
        pagination layer (see `src/framework/dispatch/pagination.py`)."""
        stmt = select(Provider)
        if license_type or issuing_state:
            stmt = stmt.join(
                ProviderLicensure,
                ProviderLicensure.provider_id == Provider.id,
            )
            if license_type:
                stmt = stmt.filter(ProviderLicensure.license_type.in_(license_type))
            if issuing_state:
                stmt = stmt.filter(ProviderLicensure.issuing_state.in_(issuing_state))
            stmt = stmt.distinct()
        stmt = stmt.order_by(Provider.created_at.desc())
        return await self._list(stmt, offset=offset, limit=limit)

    # --- Provider mutations ----------------------------------------
    # The framework's `handle_create` calls `repo.create(Provider(...))`
    # (the public alias on `BaseRepository`) directly — no `create_provider`
    # wrapper needed. Inline credential rows append via `repo.add_child`.
