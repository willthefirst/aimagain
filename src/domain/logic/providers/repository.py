from typing import Sequence
from uuid import UUID

from sqlalchemy import select

from src.domain.models import Provider, ProviderLicensure
from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import register_repository


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
        return await self.list_owned_by(Provider, user_id, offset=offset, limit=limit)

    async def list_for_verification(self) -> Sequence[Provider]:
        """Return providers eligible for the nightly verification job
        (`src/jobs/nightly_verification.py`).

        Eligibility today is the minimum that's clearly correct:
        non-deleted providers. We deliberately do NOT skip rows
        verified within the last 24h — NPPES has no published rate
        limit and the per-call timeout (10s) bounds total runtime, so
        a "verified yesterday" provider re-verifying tonight is cheap
        and keeps the daily badge fresh. Revisit this filter when
        rate-limiting actually bites or the provider count grows past
        O(1000).
        """
        return await self._list(select(Provider).filter(Provider.deleted_at.is_(None)))

    async def list_clinicians(
        self,
        *,
        license_type: list[str] | None = None,
        issuing_state: list[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> Sequence[Provider]:
        """Lists clinician directory entries (rows of the `Provider`
        model — the user-facing name flipped to "clinician" in #642
        PR 4), newest first. The method name follows the framework's
        `list_<url_collection>` convention; the underlying model
        class stays `Provider`. Both filters are multi-select lists;
        each non-empty list ANDs into the join (any-of within the
        list, all-of across filters). When either filter is set,
        joins through `provider_licensures` and `.distinct()`s the
        parents so a clinician with multiple matching licensures
        appears once. `offset`/`limit` come from the framework's
        pagination layer (see `src/framework/dispatch/pagination.py`)."""
        stmt = select(Provider)
        if license_type or issuing_state:
            stmt = stmt.join(
                ProviderLicensure,
                ProviderLicensure.clinician_id == Provider.clinician_id,
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


get_provider_repository = register_repository(ProviderRepository)
