from collections.abc import Sequence

from sqlalchemy import or_, select

from src.domain.models import ClientReferralDetail, Post, ProviderAvailabilityDetail
from src.framework.persistence.base_repository import BaseRepository


class PostRepository(BaseRepository):
    """Posts-specific reads.

    Filter axes the list page exposes via ``POST_ENTITY.filters``:

    * ``kind`` (Choice, single) — exact match on ``Post.kind``.
    * ``q`` (Text) — case-insensitive substring against the post's
      description on **either** detail table. Posts is polymorphic
      (`client_referral_detail` and `provider_availability_detail`
      are separate tables, one per row) so a free-text search has to
      ``LEFT JOIN`` both and OR the predicates. Each post has a row
      in at most one of the two — the OR coalesces them into a
      single "matches" boolean without duplicating rows.

    Empty / absent filter values short-circuit (no WHERE clause), so
    URL params that aren't set carry no SQL cost. AND-combined across
    filters; the OR is only inside a single filter's evaluation.
    """

    async def list_posts(
        self,
        *,
        kind: str | None = None,
        q: str | None = None,
    ) -> Sequence[Post]:
        stmt = select(Post)
        if kind is not None:
            stmt = stmt.filter(Post.kind == kind)
        if q:
            needle = f"%{q}%"
            stmt = (
                stmt.outerjoin(
                    ClientReferralDetail,
                    ClientReferralDetail.post_id == Post.id,
                )
                .outerjoin(
                    ProviderAvailabilityDetail,
                    ProviderAvailabilityDetail.post_id == Post.id,
                )
                .filter(
                    or_(
                        ClientReferralDetail.description.ilike(needle),
                        ProviderAvailabilityDetail.description.ilike(needle),
                    )
                )
            )
        stmt = stmt.order_by(Post.created_at.desc())
        return await self._list(stmt)
