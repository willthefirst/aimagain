import uuid
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select

from src.domain.models import Organization, Provider, ProviderLicensure
from src.framework.http.exceptions import NotFoundError
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
    #
    # The `create` / `patch` overrides below maintain the mirror invariant
    # between ``Provider.practice_name`` and ``Provider.org.name`` —
    # see ``src/domain/models/providers/README.md``. Mirrors the shape
    # of ``OrganizationRepository`` (PR 1, roadmap).
    # TODO(roadmap-pr-3): drop these overrides when ``practice_name``
    # leaves Provider and reads switch to ``provider.org.name`` directly.

    async def _find_or_create_org_for(
        self, *, owner_id: UUID, practice_name: str
    ) -> Organization:
        """Resolve the Org for a Provider whose only Org-pointer is its
        free-text ``practice_name``. PR 2 of the roadmap has no Org-
        picker UI yet, so the repository auto-routes new Providers to
        the Org with a matching name — find-or-create keyed on
        ``Organization.name``. New Orgs are ``solo_practice`` rooted at
        themselves; PR 3+ revisits classification when the explicit
        Org-create form lands."""
        stmt = select(Organization).filter(Organization.name == practice_name).limit(1)
        org = (await self.session.execute(stmt)).scalars().first()
        if org is not None:
            return org
        new_org = Organization(
            id=uuid.uuid4(),
            name=practice_name,
            type="solo_practice",
            owner_id=owner_id,
        )
        new_org.root_org_id = new_org.id
        self.session.add(new_org)
        await self.session.flush()
        await self.session.refresh(new_org)
        return new_org

    async def create(self, obj: Provider) -> Provider:
        """Override the framework's `create` to enforce the mirror
        invariant ``provider.practice_name == provider.org.name``.

        If the caller supplied ``org_id`` directly (no current writer
        does today, but tests and PR 3's create form will), the FK is
        validated and ``practice_name`` is overwritten from the Org's
        name. Otherwise the repository find-or-creates an Org keyed on
        ``practice_name``."""
        if obj.org_id is None:
            org = await self._find_or_create_org_for(
                owner_id=obj.owner_id, practice_name=obj.practice_name
            )
            obj.org_id = org.id
        else:
            org = await self._get_by_id(Organization, obj.org_id)
            if org is None:
                raise NotFoundError(
                    detail=f"Organization {obj.org_id} not found",
                )
        obj.practice_name = org.name
        return await self._persist_new(obj)

    async def patch(self, obj: Provider, **fields: Any) -> Provider:
        """Override `patch` so any change touching the mirror columns
        keeps ``practice_name`` and ``org.name`` in lockstep.

        Three cases the override handles:
        1. ``org_id`` in the payload → look up that Org, overwrite
           ``practice_name`` with its ``name`` (and drop any conflicting
           ``practice_name`` value from the payload).
        2. ``practice_name`` in the payload (and ``org_id`` not) →
           find-or-create an Org with that name, reassign ``org_id``,
           write ``practice_name`` from the resolved Org.
        3. Neither in the payload → pass straight through.
        """
        new_org_id = fields.get("org_id")
        new_practice_name = fields.get("practice_name")
        if new_org_id is not None:
            org = await self._get_by_id(Organization, new_org_id)
            if org is None:
                raise NotFoundError(
                    detail=f"Organization {new_org_id} not found",
                )
            fields["practice_name"] = org.name
        elif new_practice_name is not None and new_practice_name != obj.practice_name:
            org = await self._find_or_create_org_for(
                owner_id=obj.owner_id, practice_name=new_practice_name
            )
            fields["org_id"] = org.id
            fields["practice_name"] = org.name
        return await self._patch(obj, **fields)
