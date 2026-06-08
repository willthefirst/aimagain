"""Organization repository.

Plain `BaseRepository` over the `Organization` model. No bespoke
hierarchy logic — the entity is flat (no parent/root columns).
"""

import uuid
from typing import Sequence

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


get_organization_repository = register_repository(OrganizationRepository)
