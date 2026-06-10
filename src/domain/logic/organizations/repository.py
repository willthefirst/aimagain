"""Organization repository.

Plain `BaseRepository` over the `Organization` model. No bespoke
hierarchy logic — the entity is flat (no parent/root columns).
"""

import uuid
from typing import Sequence

import sqlalchemy as sa
from sqlalchemy import select

from src.domain.logic.capabilities import claim_state
from src.domain.models import Organization
from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import register_repository


class OrganizationRepository(BaseRepository):
    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[Organization]:
        """Lists every Organization owned by ``user_id``, newest first.
        Drives the Clinician edit form's Org-picker dropdown — users can
        only attach Clinicians to Orgs they own (#524 retro: Org
        ownership is the boundary for who may attach Clinicians,
        mirroring ``Organization.write_authz``)."""
        return await self.list_owned_by(Organization, user_id)

    async def list_organizations(
        self,
        *,
        owner: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> Sequence[Organization]:
        """List organizations newest first.

        ``owner="me"`` scopes results to the orgs the viewer is
        affiliated with — owned (``Organization.owner_id == viewer.id``)
        OR held as a verified, non-archived ``OrgRepresentation``
        (``Organization.id IN claim_state(viewer).b``). Mirrors the
        un-redacted treatment on the org card / detail templates so the
        URL filter and the per-row visibility line up. Without
        ``owner``, every org is listed (the directory page handles
        identity privacy via per-row redaction in
        ``organizations/list.html``).

        The viewer is the same id ``BaseRepository._requesting_user``
        carries — stamped by ``handle_list`` so every list mount can
        resolve viewer-relative filters. Any non-``"me"`` ``owner``
        value is silently ignored (the only supported sentinel today).
        """
        stmt = select(Organization)
        if (
            owner == "me"
            and self._requesting_user is not None
            and getattr(self._requesting_user, "id", None) is not None
        ):
            viewer = self._requesting_user
            rep_org_ids = claim_state(viewer).b
            stmt = stmt.filter(
                sa.or_(
                    Organization.owner_id == viewer.id,
                    Organization.id.in_(rep_org_ids),
                )
            )
        stmt = stmt.order_by(Organization.created_at.desc())
        return await self._list(stmt, offset=offset, limit=limit)


get_organization_repository = register_repository(OrganizationRepository)
