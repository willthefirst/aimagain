from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, or_, select

from src.domain.models import (
    ClinicianAffiliation,
    IntakeDetail,
    OpeningDetail,
    Post,
    Program,
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
    ``ClinicianAffiliation``). Each post has a row in at most one of the two
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
      linked ``ClinicianAffiliation``.
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
    * ``geography`` (Text) — ILIKE across city, state, and zip on both
      ``ReferralDetail`` (its own location) and ``ClinicianAffiliation``
      (opening/intake's linked practice location).
    * ``include_telehealth`` (Flag) — when present, expands the
      ``geography`` filter to also include openings where the linked
      ClinicianAffiliation has ``virtual_sessions='yes'`` in CA.
    * ``level_of_care`` (Choice, multi) — ``settings`` JSON-array
      contains check across ``OpeningDetail`` and ``IntakeDetail``
      (``ReferralDetail`` has no settings field and is excluded when
      this filter is active).
    * ``modality`` (Choice, multi) — ``modalities`` JSON-array contains
      check across all three detail tables.
    * ``insurance`` (Choice, multi) — ``insurance_carrier`` exact match
      on ``ReferralDetail`` OR ``in_network_carriers`` JSON-contains on
      linked ``ClinicianAffiliation``.

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
        geography: str | None = None,
        include_telehealth: str | None = None,
        level_of_care: list[str] | None = None,
        modality: list[str] | None = None,
        insurance: list[str] | None = None,
        since: datetime | None = None,
        exclude_owner_id: int | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> Sequence[Post]:
        stmt = select(Post)

        # Joins are added only when a filter that needs them is active,
        # so a bare `/posts` request stays a single-table read.
        needs_detail_join = any(
            (
                q,
                state,
                city,
                age_group,
                language,
                geography,
                include_telehealth,
                level_of_care,
                modality,
                insurance,
            )
        )
        needs_clinician_join = bool(
            state or city or geography or include_telehealth or insurance
        )
        needs_intake_join = bool(level_of_care or modality or insurance)
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
        if needs_clinician_join:
            stmt = stmt.outerjoin(
                ClinicianAffiliation,
                ClinicianAffiliation.clinician_id == OpeningDetail.clinician_id,
            )
        if needs_intake_join:
            stmt = stmt.outerjoin(
                IntakeDetail,
                IntakeDetail.post_id == Post.id,
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
                    ClinicianAffiliation.location_state.in_(state),
                )
            )
        if city:
            needle = f"%{city}%"
            stmt = stmt.filter(
                or_(
                    ReferralDetail.location_city.ilike(needle),
                    ClinicianAffiliation.location_city.ilike(needle),
                )
            )
        if age_group:
            stmt = stmt.filter(_json_array_contains_any(age_group, "age_groups"))
        if language:
            stmt = stmt.filter(_json_array_contains_any(language, "languages"))

        if geography:
            needle = f"%{geography}%"
            geo_clauses = [
                ReferralDetail.location_city.ilike(needle),
                ReferralDetail.location_state.ilike(needle),
                ReferralDetail.location_zip.ilike(needle),
                ClinicianAffiliation.location_city.ilike(needle),
                ClinicianAffiliation.location_state.ilike(needle),
                ClinicianAffiliation.location_zip.ilike(needle),
            ]
            if include_telehealth:
                geo_clauses.append(
                    and_(
                        ClinicianAffiliation.virtual_sessions == "yes",
                        ClinicianAffiliation.location_state == "CA",
                    )
                )
            stmt = stmt.filter(or_(*geo_clauses))
        # include_telehealth alone (no geography) adds no constraint — it
        # only expands the geography filter when both are active.

        if level_of_care:
            clauses = []
            for v in level_of_care:
                token = f'%"{v}"%'
                clauses.append(
                    or_(
                        OpeningDetail.settings.like(token),
                        IntakeDetail.settings.like(token),
                    )
                )
            stmt = stmt.filter(or_(*clauses))

        if modality:
            stmt = stmt.filter(_json_array_contains_any_three(modality, "modalities"))

        if insurance:
            clauses = []
            for v in insurance:
                token = f'%"{v}"%'
                clauses.append(
                    or_(
                        ReferralDetail.insurance_carrier == v,
                        ClinicianAffiliation.in_network_carriers.like(token),
                    )
                )
            stmt = stmt.filter(or_(*clauses))

        if since is not None:
            stmt = stmt.filter(Post.created_at >= since)
        if exclude_owner_id is not None:
            stmt = stmt.filter(Post.owner_id != exclude_owner_id)

        stmt = stmt.order_by(Post.created_at.desc())
        return await self._list(stmt, offset=offset, limit=limit)

    # Owner-scoped read projections (RESOURCE_GRAMMAR pattern #5). Each
    # is the same supertype rows narrowed to one owner; the inner join to
    # a detail table already restricts to the matching kind (a post has a
    # row in exactly one detail table), so no `Post.kind` literal is
    # needed here.
    async def list_clinician_openings(
        self, clinician_id, *, offset: int = 0, limit: int | None = None
    ) -> Sequence[Post]:
        stmt = (
            select(Post)
            .join(OpeningDetail, OpeningDetail.post_id == Post.id)
            .filter(OpeningDetail.clinician_id == clinician_id)
            .order_by(Post.created_at.desc())
        )
        return await self._list(stmt, offset=offset, limit=limit)

    async def list_clinician_referrals(
        self, clinician_id, *, offset: int = 0, limit: int | None = None
    ) -> Sequence[Post]:
        # Scoped by the referral's designated referring clinician — the
        # same FK the post-create authz treats as referral ownership.
        stmt = (
            select(Post)
            .join(ReferralDetail, ReferralDetail.post_id == Post.id)
            .filter(ReferralDetail.referring_clinician_id == clinician_id)
            .order_by(Post.created_at.desc())
        )
        return await self._list(stmt, offset=offset, limit=limit)

    async def list_org_intakes(
        self, org_id, *, offset: int = 0, limit: int | None = None
    ) -> Sequence[Post]:
        stmt = (
            select(Post)
            .join(IntakeDetail, IntakeDetail.post_id == Post.id)
            .join(Program, Program.id == IntakeDetail.program_id)
            .filter(Program.org_id == org_id)
            .order_by(Post.created_at.desc())
        )
        return await self._list(stmt, offset=offset, limit=limit)

    # The single `/posts` URL family lists every kind through
    # `list_posts`. `handle_list` looks up
    # `repo.list_<spec.url_collection>`, so the spec's `url_collection`
    # ("posts") resolves directly to `list_posts`. The thin shims below
    # remain for any callers still wired to the per-kind method names.
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


def _json_array_contains_any_three(values: list[str], column_name: str):
    """Like ``_json_array_contains_any`` but also checks ``IntakeDetail``.

    Used for fields that exist on all three detail tables (currently
    ``modalities``). Requires ``IntakeDetail`` to be joined before the
    predicate is applied.
    """
    cr_col = getattr(ReferralDetail, column_name)
    pa_col = getattr(OpeningDetail, column_name)
    pi_col = getattr(IntakeDetail, column_name)
    clauses = []
    for v in values:
        token = f'%"{v}"%'
        clauses.append(or_(cr_col.like(token), pa_col.like(token), pi_col.like(token)))
    return or_(*clauses)


get_post_repository = register_repository(PostRepository)
