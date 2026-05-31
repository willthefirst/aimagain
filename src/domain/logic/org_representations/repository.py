"""Persistence for `OrgRepresentation` (Claim B / User↔Org authority)."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select

from src.domain.models import OrgRepresentation
from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import register_repository


class OrgRepresentationRepository(BaseRepository):
    async def get_active_by_pair(
        self, *, user_id: UUID, org_id: UUID
    ) -> OrgRepresentation | None:
        """Lookup an *active* representation (i.e. not archived) for the
        given (user, org). Used by the capability predicate
        `org_rep_verified(user, org)` and the rep-approval handler."""
        stmt = select(OrgRepresentation).filter(
            OrgRepresentation.user_id == user_id,
            OrgRepresentation.org_id == org_id,
            OrgRepresentation.archived_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_verified_for_user(
        self, user_id: UUID
    ) -> Sequence[OrgRepresentation]:
        """All currently-verified representations a user holds. Drives
        `capabilities.claim_state(user).b`."""
        stmt = select(OrgRepresentation).filter(
            OrgRepresentation.user_id == user_id,
            OrgRepresentation.authority_status == "verified",
            OrgRepresentation.archived_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_verified_for_org(self, org_id: UUID) -> Sequence[OrgRepresentation]:
        """All currently-verified reps acting for an org. Used by the
        rep-approval path: a new pending row needs an existing verified
        approver on the same org."""
        stmt = select(OrgRepresentation).filter(
            OrgRepresentation.org_id == org_id,
            OrgRepresentation.authority_status == "verified",
            OrgRepresentation.archived_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


get_org_representation_repository = register_repository(OrgRepresentationRepository)
