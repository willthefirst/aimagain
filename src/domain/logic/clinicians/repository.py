from typing import Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import select

from src.domain.models import Clinician, ClinicianLicensure, UserFavorite
from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import register_repository


class ClinicianRepository(BaseRepository):
    async def get_by_user_id(self, user_id: UUID) -> Clinician | None:
        stmt = select(Clinician).filter(Clinician.owner_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> Sequence[Clinician]:
        return await self.list_owned_by(Clinician, user_id, offset=offset, limit=limit)

    async def list_clinicians(
        self,
        *,
        license_type: list[str] | None = None,
        issuing_state: list[str] | None = None,
        owner: str | None = None,
        favorited: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> Sequence[Clinician]:
        """List directory entries newest first. Filters are multi-select
        unless noted; when set, the licensure filters join through
        `clinician_licensures` (SQL table) and distinct so a clinician
        with multiple matching licensures appears once.

        Per handoff §4.3 + §10.6, the directory only surfaces clinicians
        with `clinician_verified=True` OR `ever_verified_at IS NOT NULL`:

        * `clinician_verified=True` — actively verified Claim A.
        * `ever_verified_at IS NOT NULL` — once-verified clinician
          whose claim has lapsed (per §10.6 they "stay listed but hide
          open posts" — listing them keeps the directory page useful,
          their post visibility is gated separately by the capability
          predicates).

        Never-verified clinicians are filtered out so the directory
        stays a curated index of verified providers — the chrome's
        capability gates already prevent them from posting, and listing
        them would surface noise. **Exception:** the viewer's *own*
        clinician rows are always included regardless of verification
        state. A brand-new user's in-flight clinician (sitting in the
        NPPES queue, not yet ``clinician_verified``) must remain
        visible to its creator so they can find and edit it, even on
        the unfiltered `/clinicians` page. The redaction layer keeps
        other viewers from leaking the identity — the universe never
        narrows for the owner.

        ``owner="me"`` scopes results to the viewer's own rows
        (``Clinician.owner_id == self._requesting_user.id``) and drops
        the verified-only filter entirely — useful when the picker
        deep-links here. The viewer is the same id
        ``BaseRepository._requesting_user`` carries — stamped by
        ``handle_list`` so every list mount can resolve viewer-relative
        filters. Any other ``owner`` value is silently ignored (the
        only supported sentinel today).

        ``favorited="me"`` scopes results to the clinicians the viewer
        has favorited (``Clinician.id IN (SELECT clinician_id FROM
        user_favorites WHERE user_id = viewer)``) and likewise bypasses
        the verified-only gate — a favorited clinician stays reachable
        through this filter even if their verification later lapses.
        This replaces the standalone `/users/me/favorites` page: favorites
        are now a viewer-relative quality of the clinician directory.
        Mutually exclusive with ``owner`` in practice (separate single
        toggles); if both are "me", ``owner`` wins.
        """
        viewer_id = (
            self._requesting_user.id
            if self._requesting_user is not None
            and getattr(self._requesting_user, "id", None) is not None
            else None
        )
        owner_self = owner == "me" and viewer_id is not None
        favorited_self = favorited == "me" and viewer_id is not None
        if owner_self:
            stmt = select(Clinician).filter(Clinician.owner_id == viewer_id)
        elif favorited_self:
            favorited_ids = select(UserFavorite.clinician_id).filter(
                UserFavorite.user_id == viewer_id
            )
            stmt = select(Clinician).filter(Clinician.id.in_(favorited_ids))
        else:
            # Default directory: verified-only. The viewer's own rows
            # bypass the gate so brand-new in-flight clinicians stay
            # visible to their creator while NPPES verification is in
            # progress.
            verified_or_own = sa.or_(
                Clinician.clinician_verified.is_(True),
                Clinician.ever_verified_at.is_not(None),
            )
            if viewer_id is not None:
                verified_or_own = sa.or_(
                    verified_or_own,
                    Clinician.owner_id == viewer_id,
                )
            stmt = select(Clinician).filter(verified_or_own)
        if license_type or issuing_state:
            stmt = stmt.join(
                ClinicianLicensure,
                ClinicianLicensure.clinician_id == Clinician.id,
            )
            if license_type:
                stmt = stmt.filter(ClinicianLicensure.license_type.in_(license_type))
            if issuing_state:
                stmt = stmt.filter(ClinicianLicensure.issuing_state.in_(issuing_state))
            stmt = stmt.distinct()
        stmt = stmt.order_by(Clinician.created_at.desc())
        return await self._list(stmt, offset=offset, limit=limit)


get_clinician_repository = register_repository(ClinicianRepository)
