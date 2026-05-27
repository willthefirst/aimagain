from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import or_, select

from src.domain.models import (
    Affiliation,
    OpeningDetail,
    Post,
    ReferralDetail,
    User,
)
from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import register_repository


class PostRepository(BaseRepository):
    """Posts-specific reads.

    Every column rendered on `/posts` is filterable. The polymorphic
    body means most predicates ``OR`` across two paths — the
    seeking side reads from ``ReferralDetail``, the offering
    side from ``OpeningDetail`` (and its linked
    ``Affiliation``). Each post has a row in at most one of the two
    detail tables, so the ``OR`` coalesces the two paths into a
    single "matches" boolean without duplicating rows.

    Filter axes declared on ``POST_ENTITY.filters``:

    * ``kind`` (Choice) — exact match on ``Post.kind``.
    * ``q`` (Text) — ILIKE substring over both detail tables'
      ``description``.
    * ``posted_by`` (Text) — ILIKE substring over the owner's
      ``username``.
    * ``state`` (Choice, multi) — ``location_state`` ``IN`` across
      ``ReferralDetail`` (seeking) and the offering side's
      linked ``Affiliation``.
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
        kind: str | list[str] | None = None,
        q: str | None = None,
        posted_by: str | None = None,
        state: list[str] | None = None,
        city: str | None = None,
        age_group: list[str] | None = None,
        language: list[str] | None = None,
        since: datetime | None = None,
        exclude_owner_id: int | None = None,
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
                ReferralDetail,
                ReferralDetail.post_id == Post.id,
            ).outerjoin(
                OpeningDetail,
                OpeningDetail.post_id == Post.id,
            )
        if needs_provider_join:
            stmt = stmt.outerjoin(
                Affiliation,
                Affiliation.clinician_id == OpeningDetail.clinician_id,
            )

        if kind is not None:
            # `kind` accepts a single string (kind-locked face) or a list
            # (subset-supertype face). The framework's `handle_list` passes
            # a list when the spec declares `discriminator_values`.
            if isinstance(kind, list):
                stmt = stmt.filter(Post.kind.in_(kind))
            else:
                stmt = stmt.filter(Post.kind == kind)
        if q:
            needle = f"%{q}%"
            stmt = stmt.filter(
                or_(
                    ReferralDetail.description.ilike(needle),
                    OpeningDetail.description.ilike(needle),
                )
            )
        if posted_by:
            stmt = stmt.filter(User.username.ilike(f"%{posted_by}%"))
        if state:
            stmt = stmt.filter(
                or_(
                    ReferralDetail.location_state.in_(state),
                    Affiliation.location_state.in_(state),
                )
            )
        if city:
            needle = f"%{city}%"
            stmt = stmt.filter(
                or_(
                    ReferralDetail.location_city.ilike(needle),
                    Affiliation.location_city.ilike(needle),
                )
            )
        if age_group:
            stmt = stmt.filter(_json_array_contains_any(age_group, "age_groups"))
        if language:
            stmt = stmt.filter(_json_array_contains_any(language, "languages"))
        if since is not None:
            stmt = stmt.filter(Post.created_at >= since)
        if exclude_owner_id is not None:
            stmt = stmt.filter(Post.owner_id != exclude_owner_id)

        stmt = stmt.order_by(Post.created_at.desc())
        return await self._list(stmt, offset=offset, limit=limit)

    # The three URL families (`/referrals`, `/openings`, `/intakes`)
    # all route their list through `list_posts` — the `kind` kwarg is
    # forced by the framework's `discriminator_value` lock before the
    # call lands here. `handle_list` looks up
    # `repo.list_<spec.url_collection>`, so each face needs its own
    # method name that delegates. Three thin shims keep the convention
    # (one bespoke-named method per spec) without duplicating the SQL.
    async def list_referrals(self, **kwargs) -> Sequence[Post]:
        return await self.list_posts(**kwargs)

    async def list_openings(self, **kwargs) -> Sequence[Post]:
        return await self.list_posts(**kwargs)

    async def list_intakes(self, **kwargs) -> Sequence[Post]:
        return await self.list_posts(**kwargs)

    async def list_recent_for_network(self, **kwargs) -> Sequence[Post]:
        return await self.list_posts(**kwargs)


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
    cr_col = getattr(ReferralDetail, column_name)
    pa_col = getattr(OpeningDetail, column_name)
    clauses = []
    for v in values:
        token = f'%"{v}"%'
        clauses.append(or_(cr_col.like(token), pa_col.like(token)))
    return or_(*clauses)


get_post_repository = register_repository(PostRepository)
