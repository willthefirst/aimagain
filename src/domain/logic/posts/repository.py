from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, or_, select

from src.domain.models import (
    Clinician,
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
    body means most predicates ``OR`` across paths. The opening side now
    carries its announcement profile (services / age_groups / genders /
    session_format / cost) on ``OpeningDetail`` itself; only location +
    insurance read from its linked ``ClinicianAffiliation``. The intake
    side still reads its steady-state profile from ``IntakeDetail``'s
    linked ``Program``. The seeking side reads from ``ReferralDetail``.

    Filter axes declared on ``POST_ENTITY.filters``:

    * ``kind`` (Choice) — exact match on ``Post.kind``.
    * ``q`` (Text) — ILIKE substring over both detail tables'
      ``description``.
    * ``posted_by`` (Text) — ILIKE substring over the owner's
      ``username``.
    * ``state`` (Choice, multi) — ``location_state`` ``IN`` across
      ``ReferralDetail`` (seeking) and the offering side's linked
      ``ClinicianAffiliation``.
    * ``city`` (Text) — ILIKE substring across the same two location
      paths as ``state``.
    * ``age_group`` (Choice, multi) — JSON-array contains check on
      ``ReferralDetail.age_groups``, ``OpeningDetail.age_groups``, and
      ``IntakeDetail.age_groups`` — all per-announcement now. Uses
      ``LIKE '%"<token>"%'`` against the JSON-as-text representation —
      portable across SQLite (dev/test) without a JSON-specific extension;
      Postgres would prefer ``@>``/``?|`` operators on a ``JSONB`` column.
    * ``language`` (Choice, multi) — same JSON contains pattern against
      ``ReferralDetail.languages``, ``Clinician.languages``
      (opening-side, person-level), and ``Program.languages``
      (intake-side, program-level).
    * ``geography`` (Text) — ILIKE across city and state on both
      ``ReferralDetail`` (its own location) and ``ClinicianAffiliation``
      (opening/intake's linked practice location). No ZIP — neither side
      models one.
    * ``include_telehealth`` (Flag) — when present, expands the
      ``geography`` filter to also include openings whose own
      ``session_format`` contains ``virtual`` and whose linked
      affiliation is licensed in CA.
    * ``insurance`` (Choice, multi) — ``insurance_carriers`` JSON-array
      contains check on ``ReferralDetail`` OR ``in_network_carriers``
      JSON-contains on linked ``ClinicianAffiliation`` (#1358 PR-e —
      both sides are now JSON arrays of `INSURANCE_CARRIERS` tokens).

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
                insurance,
            )
        )
        # Both provider post kinds carry their announcement profile
        # (services / age_groups / genders / cost) on the detail row now;
        # only steady-state *context* reads from the linked entity. So:
        # ``ClinicianAffiliation`` joins for the opening's location +
        # insurance; ``Program`` joins only for the intake's program-level
        # ``languages``; ``Clinician`` joins only for the opening's
        # person-level ``languages``; ``IntakeDetail`` joins for the
        # intake's own ``age_groups`` (and as the ``Program`` join key).
        needs_clinician_join = bool(
            state or city or geography or include_telehealth or insurance
        )
        needs_owner_join = bool(posted_by)
        needs_intake_join = bool(age_group or language)
        needs_program_join = bool(language)
        needs_person_join = bool(language)

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
        if needs_program_join:
            # Join the intake detail too (if not already in) so the
            # Program join key resolves on intake rows. ``outerjoin``
            # against the same target is a SQL error in SQLAlchemy, so
            # guard with the existing ``needs_intake_join`` flag.
            if not needs_intake_join:
                stmt = stmt.outerjoin(IntakeDetail, IntakeDetail.post_id == Post.id)
            stmt = stmt.outerjoin(Program, Program.id == IntakeDetail.program_id)
        if needs_person_join:
            stmt = stmt.outerjoin(Clinician, Clinician.id == OpeningDetail.clinician_id)

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
            # Per-announcement on all three detail rows now: ReferralDetail
            # (one client), OpeningDetail + IntakeDetail (the cohort the
            # opening / intake serves).
            stmt = stmt.filter(
                _json_array_contains_any_multi(
                    age_group,
                    (
                        (ReferralDetail, "age_groups"),
                        (OpeningDetail, "age_groups"),
                        (IntakeDetail, "age_groups"),
                    ),
                )
            )
        if language:
            # Steady-state home: Clinician (opening — person-level) /
            # Program (intake — program-level). CR's ``languages`` stays
            # on ReferralDetail (no steady-state home on referrals).
            stmt = stmt.filter(
                _json_array_contains_any_multi(
                    language,
                    (
                        (ReferralDetail, "languages"),
                        (Clinician, "languages"),
                        (Program, "languages"),
                    ),
                )
            )

        if geography:
            needle = f"%{geography}%"
            geo_clauses = [
                ReferralDetail.location_city.ilike(needle),
                ReferralDetail.location_state.ilike(needle),
                ClinicianAffiliation.location_city.ilike(needle),
                ClinicianAffiliation.location_state.ilike(needle),
            ]
            if include_telehealth:
                # Telehealth is now per-announcement (the opening's
                # `session_format`), paired with the affiliation's CA
                # licensing state.
                geo_clauses.append(
                    and_(
                        OpeningDetail.session_format.like('%"virtual"%'),
                        ClinicianAffiliation.location_state == "CA",
                    )
                )
            stmt = stmt.filter(or_(*geo_clauses))
        # include_telehealth alone (no geography) adds no constraint — it
        # only expands the geography filter when both are active.

        # `level_of_care` (settings) and `modality` filters were removed:
        # no post kind models treatment settings or modalities anymore —
        # services collapsed onto the single `ReferralService` "what care"
        # axis across all three kinds.

        if insurance:
            clauses = []
            for v in insurance:
                token = f'%"{v}"%'
                clauses.append(
                    or_(
                        ReferralDetail.insurance_carriers.like(token),
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


def _json_array_contains_any_multi(
    values: Sequence[str], targets: Sequence[tuple[type, str]]
):
    """Return a WHERE predicate matching rows where any of ``values``
    appears in the JSON array on any of the ``(model, column)``
    ``targets``.

    SQLite-portable: matches ``%"<token>"%`` against the JSON column
    cast as text. The double-quote delimiters prevent prefix-collision
    between tokens (e.g. ``"en"`` vs ``"en_GB"``) and prevent substring
    matches against unrelated free-text fields that happen to share a
    column name (none today, but cheap insurance).

    When this table moves to Postgres with a ``JSONB`` column, prefer
    ``col ?| array[values]`` over this LIKE-based predicate.

    Replaces the older ``_json_array_contains_any`` / ``_three``
    helpers — #1358 PR-f introduced a third source (the steady-state
    home: ClinicianAffiliation / Program / Clinician), and a single
    variadic helper avoids a third per-arity variant.
    """
    cols = [getattr(model, column) for model, column in targets]
    clauses = []
    for v in values:
        token = f'%"{v}"%'
        clauses.append(or_(*(col.like(token) for col in cols)))
    return or_(*clauses)


get_post_repository = register_repository(PostRepository)
