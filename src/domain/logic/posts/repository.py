from collections.abc import Sequence
from datetime import datetime
from typing import Any

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

# #1358 PR-f sub-PR 2 — steady-state profile columns mirrored from the
# detail row onto its linked steady-state home. Opening side: services,
# settings, modalities, age_groups, genders, website,
# referral_instructions go on `ClinicianAffiliation`; `languages` goes
# on `Clinician`. Intake side: the same set goes on `Program`, with
# `languages` also there (program-level, not person-level). The detail
# row keeps the column during this PR's dual-write window; sub-PR 3
# drops them.
_AFFILIATION_PROFILE_COLS: tuple[str, ...] = (
    "services",
    "settings",
    "modalities",
    "age_groups",
    "genders",
    "website",
    "referral_instructions",
)
_PROGRAM_PROFILE_COLS: tuple[str, ...] = (*_AFFILIATION_PROFILE_COLS, "languages")


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
    * ``age_group`` (Choice, multi) — JSON-array contains check on the
      ``age_groups`` columns of ``ReferralDetail``, ``OpeningDetail``,
      ``ClinicianAffiliation`` (the opening-side new home, #1358 PR-f
      sub-2), and ``Program`` (the intake-side new home). Uses
      ``LIKE '%"<token>"%'`` against the JSON-as-text representation
      — portable across SQLite (dev/test) without a JSON-specific
      extension; Postgres would prefer ``@>``/``?|`` operators on a
      ``JSONB`` column when this table moves there.
    * ``language`` (Choice, multi) — same JSON contains pattern against
      ``ReferralDetail.languages``, ``OpeningDetail.languages``,
      ``Clinician.languages`` (the opening-side new home — person-
      level), and ``Program.languages`` (the intake-side new home).
    * ``geography`` (Text) — ILIKE across city, state, and zip on both
      ``ReferralDetail`` (its own location) and ``ClinicianAffiliation``
      (opening/intake's linked practice location).
    * ``include_telehealth`` (Flag) — when present, expands the
      ``geography`` filter to also include openings where the linked
      ClinicianAffiliation has ``virtual_sessions='yes'`` in CA.
    * ``level_of_care`` (Choice, multi) — ``settings`` JSON-array
      contains check across ``OpeningDetail`` / ``IntakeDetail`` and
      their new homes ``ClinicianAffiliation`` / ``Program``
      (``ReferralDetail`` has no settings field and is excluded when
      this filter is active).
    * ``modality`` (Choice, multi) — ``modalities`` JSON-array contains
      check across all three detail tables plus the new homes
      ``ClinicianAffiliation`` (opening) / ``Program`` (intake).
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
        # #1358 PR-f sub-PR 2 — the steady-state profile (services,
        # settings, modalities, age_groups, genders, languages,
        # in/out-of-network carriers, etc.) now lives on
        # ``ClinicianAffiliation`` / ``Clinician`` / ``Program``.
        # ``ClinicianAffiliation`` is also where the opening-side
        # profile filters now read from (services/settings/modalities/
        # age_groups), so any filter that needs an affiliation column
        # adds the join. ``Program`` joins whenever an intake-side
        # profile filter is active. ``Clinician`` comes in only for
        # ``language`` (the one column whose new home is the person,
        # not the affiliation). Dual-write keeps the old detail columns
        # in lockstep during this PR's window, so each filter clause
        # ORs the new-home column with the detail-row column for
        # safety; sub-PR 3 collapses to new-home only.
        needs_clinician_join = bool(
            state
            or city
            or geography
            or include_telehealth
            or insurance
            or age_group
            or level_of_care
            or modality
        )
        needs_intake_join = bool(level_of_care or modality or insurance)
        needs_owner_join = bool(posted_by)
        needs_program_join = bool(level_of_care or modality or age_group or language)
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
            # New home: ClinicianAffiliation (opening) / Program (intake).
            # Detail rows kept as the dual-write fallback arm. CR's
            # ``age_groups`` stays on ReferralDetail (referrals describe
            # one client and have no steady-state home).
            stmt = stmt.filter(
                _json_array_contains_any_multi(
                    age_group,
                    (
                        (ReferralDetail, "age_groups"),
                        (OpeningDetail, "age_groups"),
                        (ClinicianAffiliation, "age_groups"),
                        (Program, "age_groups"),
                    ),
                )
            )
        if language:
            # New home: Clinician (opening — person-level) / Program
            # (intake — program-level). Detail rows kept as the dual-
            # write fallback arm. CR's ``languages`` stays on
            # ReferralDetail (no steady-state home on referrals).
            stmt = stmt.filter(
                _json_array_contains_any_multi(
                    language,
                    (
                        (ReferralDetail, "languages"),
                        (OpeningDetail, "languages"),
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
            # New home: ClinicianAffiliation (opening) / Program
            # (intake). Detail rows OR'd in as dual-write fallback.
            stmt = stmt.filter(
                _json_array_contains_any_multi(
                    level_of_care,
                    (
                        (OpeningDetail, "settings"),
                        (IntakeDetail, "settings"),
                        (ClinicianAffiliation, "settings"),
                        (Program, "settings"),
                    ),
                )
            )

        if modality:
            # New home: ClinicianAffiliation (opening) / Program
            # (intake). CR's ``modalities`` stays on ReferralDetail
            # (no steady-state home). Detail rows OR'd in as dual-write
            # fallback.
            stmt = stmt.filter(
                _json_array_contains_any_multi(
                    modality,
                    (
                        (ReferralDetail, "modalities"),
                        (OpeningDetail, "modalities"),
                        (IntakeDetail, "modalities"),
                        (ClinicianAffiliation, "modalities"),
                        (Program, "modalities"),
                    ),
                )
            )

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

    # #1358 PR-f sub-PR 2 — dual-write override hooks. The framework's
    # generic polymorphic create/update mounts call `create_polymorphic`
    # and `patch` here; this layer extends both to mirror the steady-
    # state profile fields onto the linked ClinicianAffiliation /
    # Clinician / Program so reads from the new homes (see the view layer
    # flip) stay consistent. Sub-PR 3 removes the per-announcement
    # columns and this dual-write goes away — only the new-home write
    # path remains.
    async def create_polymorphic(
        self, parent: Any, detail: Any, *, detail_relationship: str
    ) -> Any:
        created = await super().create_polymorphic(
            parent, detail, detail_relationship=detail_relationship
        )
        await self._mirror_detail_to_steady_state_home(detail)
        return created

    async def patch(self, obj: Any, **fields: Any) -> Any:
        patched = await super().patch(obj, **fields)
        if isinstance(obj, (OpeningDetail, IntakeDetail)):
            await self._mirror_detail_to_steady_state_home(patched)
        return patched

    async def _mirror_detail_to_steady_state_home(self, detail: Any) -> None:
        """Copy the steady-state profile fields off a fresh / patched
        OpeningDetail or IntakeDetail onto the linked home row
        (Affiliation + Clinician for openings; Program for intakes).

        Only mirrors fields the caller actually set on the detail row
        (``None`` is skipped) so a PATCH that touches only `description`
        doesn't trample the affiliation's existing profile with a null
        from the detail row. List fields with an empty `[]` value are
        skipped on the same principle — an explicit clear has no
        wire path that hits only the old column today.
        """
        if isinstance(detail, OpeningDetail):
            await self._mirror_opening_detail(detail)
        elif isinstance(detail, IntakeDetail):
            await self._mirror_intake_detail(detail)

    async def _mirror_opening_detail(self, detail: OpeningDetail) -> None:
        affiliation_id = detail.clinician_affiliation_id
        if affiliation_id is not None:
            affiliation = await self.get_by_model_id(
                ClinicianAffiliation, affiliation_id
            )
            if affiliation is not None:
                self._copy_nonempty(detail, affiliation, _AFFILIATION_PROFILE_COLS)
                self.session.add(affiliation)
        clinician_id = detail.clinician_id
        if clinician_id is not None:
            clinician = await self.get_by_model_id(Clinician, clinician_id)
            if clinician is not None:
                self._copy_nonempty(detail, clinician, ("languages",))
                self.session.add(clinician)
        await self.session.flush()

    async def _mirror_intake_detail(self, detail: IntakeDetail) -> None:
        program_id = detail.program_id
        if program_id is None:
            return
        program = await self.get_by_model_id(Program, program_id)
        if program is None:
            return
        self._copy_nonempty(detail, program, _PROGRAM_PROFILE_COLS)
        self.session.add(program)
        await self.session.flush()

    @staticmethod
    def _copy_nonempty(src: Any, dst: Any, cols: Sequence[str]) -> None:
        """Copy each column in ``cols`` from ``src`` to ``dst`` when
        the source value is set (not ``None``, not empty list). An
        empty value on the source means "the writer didn't touch this
        field" — we leave whatever's on ``dst``. This is the dual-write
        invariant for the PR-f sub-PR 2 window: every write that lands
        a value on the detail row also lands it on the new home, but no
        write nulls a new-home value via the detail mirror."""
        for col in cols:
            value = getattr(src, col, None)
            if value is None:
                continue
            if isinstance(value, list) and not value:
                continue
            setattr(dst, col, value)

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

    Replaces the older ``_json_array_contains_any`` /
    ``_three`` helpers — #1358 PR-f sub-PR 2 added a third source
    (the steady-state home: ClinicianAffiliation / Program /
    Clinician), and a single variadic helper avoids a third per-arity
    variant.
    """
    cols = [getattr(model, column) for model, column in targets]
    clauses = []
    for v in values:
        token = f'%"{v}"%'
        clauses.append(or_(*(col.like(token) for col in cols)))
    return or_(*clauses)


get_post_repository = register_repository(PostRepository)
