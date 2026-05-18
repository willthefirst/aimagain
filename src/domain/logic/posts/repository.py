from collections.abc import Sequence

from sqlalchemy import or_, select

from src.domain.models import (
    ClientReferralDetail,
    Post,
    Provider,
    ProviderAvailabilityDetail,
    User,
)
from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import register_repository


class PostRepository(BaseRepository):
    """Posts-specific reads.

    Every column rendered on `/posts` is filterable. The polymorphic
    body means most predicates ``OR`` across two paths — the
    seeking side reads from ``ClientReferralDetail``, the offering
    side from ``ProviderAvailabilityDetail`` (and its linked
    ``Provider``). Each post has a row in at most one of the two
    detail tables, so the ``OR`` coalesces the two paths into a
    single "matches" boolean without duplicating rows.

    Filter axes declared on ``POST_ENTITY.filters``:

    * ``kind`` (Choice) — exact match on ``Post.kind``.
    * ``q`` (Text) — ILIKE substring over both detail tables'
      ``description``.
    * ``posted_by`` (Text) — ILIKE substring over the owner's
      ``username``.
    * ``state`` (Choice, multi) — ``location_state`` ``IN`` across
      ``ClientReferralDetail`` (seeking) and the offering side's
      linked ``Provider``.
    * ``city`` (Text) — ILIKE substring across the same two location
      paths as ``state``.
    * ``age_group`` (Choice, multi) — JSON-array contains check on
      both detail tables' ``age_groups``. Uses ``LIKE '%"<token>"%'``
      against the JSON-as-text representation — portable across
      SQLite (dev/test) without a JSON-specific extension; Postgres
      would prefer ``@>``/``?|`` operators on a ``JSONB`` column when
      this table moves there.
    * ``language`` (Choice, multi) — same JSON contains pattern
      against both detail tables' ``languages``.

    Empty / absent filter values short-circuit (no WHERE clause), so
    URL params that aren't set carry no SQL cost. AND-combined across
    filters; within a multi-value Choice values are OR-combined.
    """

    async def list_posts(
        self,
        *,
        kind: str | None = None,
        q: str | None = None,
        posted_by: str | None = None,
        state: list[str] | None = None,
        city: str | None = None,
        age_group: list[str] | None = None,
        language: list[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> Sequence[Post]:
        stmt = select(Post)

        # Joins are added only when a filter that needs them is active,
        # so a bare `/posts` request stays a single-table read.
        needs_detail_join = any((q, state, city, age_group, language))
        needs_provider_join = bool(state or city)
        needs_owner_join = bool(posted_by)

        if needs_owner_join:
            stmt = stmt.outerjoin(User, User.id == Post.owner_id)
        if needs_detail_join:
            stmt = stmt.outerjoin(
                ClientReferralDetail,
                ClientReferralDetail.post_id == Post.id,
            ).outerjoin(
                ProviderAvailabilityDetail,
                ProviderAvailabilityDetail.post_id == Post.id,
            )
        if needs_provider_join:
            stmt = stmt.outerjoin(
                Provider,
                Provider.id == ProviderAvailabilityDetail.provider_id,
            )

        if kind is not None:
            stmt = stmt.filter(Post.kind == kind)
        if q:
            needle = f"%{q}%"
            stmt = stmt.filter(
                or_(
                    ClientReferralDetail.description.ilike(needle),
                    ProviderAvailabilityDetail.description.ilike(needle),
                )
            )
        if posted_by:
            stmt = stmt.filter(User.username.ilike(f"%{posted_by}%"))
        if state:
            stmt = stmt.filter(
                or_(
                    ClientReferralDetail.location_state.in_(state),
                    Provider.location_state.in_(state),
                )
            )
        if city:
            needle = f"%{city}%"
            stmt = stmt.filter(
                or_(
                    ClientReferralDetail.location_city.ilike(needle),
                    Provider.location_city.ilike(needle),
                )
            )
        if age_group:
            stmt = stmt.filter(_json_array_contains_any(age_group, "age_groups"))
        if language:
            stmt = stmt.filter(_json_array_contains_any(language, "languages"))

        stmt = stmt.order_by(Post.created_at.desc())
        return await self._list(stmt, offset=offset, limit=limit)


def _json_array_contains_any(values: list[str], column_name: str):
    """Return a WHERE predicate matching rows where ``column_name``'s
    JSON array contains any of ``values`` on either detail table.

    SQLite-portable: matches ``%"<token>"%`` against the JSON column
    cast as text. The double-quote delimiters prevent prefix-collision
    between tokens (e.g. ``"en"`` vs ``"en_GB"``) and prevent substring
    matches against unrelated free-text fields that happen to share a
    column name (none today, but cheap insurance).

    When this table moves to Postgres with a ``JSONB`` column, prefer
    ``col ?| array[values]`` over this LIKE-based predicate.
    """
    cr_col = getattr(ClientReferralDetail, column_name)
    pa_col = getattr(ProviderAvailabilityDetail, column_name)
    clauses = []
    for v in values:
        token = f'%"{v}"%'
        clauses.append(or_(cr_col.like(token), pa_col.like(token)))
    return or_(*clauses)


get_post_repository = register_repository(PostRepository)
