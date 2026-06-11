"""Tests for `Post` persistence invariants.

Exercises the parent + per-kind-detail invariants the polymorphic-create
path owns: create persists both rows in one flush, update writes per-kind
fields to the correct detail row, delete cascades the detail via the FK.
Covered for `kind='referral'` and `kind='clinician_opening'`.

Posts have no bespoke repo class — these tests drive `BaseRepository`
directly, which is what the framework injects for the post route.
"""

import uuid

import pytest
from sqlalchemy import bindparam, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.types import Uuid

from src.domain.models import (
    IntakeDetail,
    OpeningDetail,
    Post,
    ReferralDetail,
)
from src.framework.persistence.base_repository import BaseRepository
from tests.helpers import (
    create_test_user,
    make_clinician_with_org,
    make_intake_detail,
    make_opening_detail,
    make_organization_row,
    make_program,
    make_referral_detail,
)

pytestmark = pytest.mark.asyncio


async def _seed_owner(db_test_session_manager):
    owner = create_test_user(username=f"owner-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
    return owner


async def _seed_owner_and_clinician(db_test_session_manager, **clinician_overrides):
    """Seed a User + a Clinician owned by them. Returns `(owner, clinician)`.

    PA detail rows point at a Clinician via `clinician_id` FK; persistence
    tests that flush a `OpeningDetail` need a real clinician row
    in the DB to satisfy the FK.
    """
    owner = create_test_user(username=f"owner-{uuid.uuid4()}")
    clinician = make_clinician_with_org(owner_id=owner.id, **clinician_overrides)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            session.add(clinician)
    return owner, clinician


async def _create_post(repo, post, detail):
    """Test helper: persist a Post + detail using the framework's
    `create_polymorphic` (which lifted post-repo's `_attach_detail`
    into BaseRepository in B2 / #328)."""
    from src.domain.models import POST_KIND_BY_DETAIL_MODEL

    kind_spec = POST_KIND_BY_DETAIL_MODEL[type(detail)]
    return await repo.create_polymorphic(
        post, detail, detail_relationship=kind_spec.detail_relationship
    )


# --- Raw-SQL CASCADE check ----------------------------------------------


async def test_raw_sql_delete_post_cascades_via_fk(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A raw-SQL DELETE bypasses the ORM cascade — only the FK CASCADE can
    remove the detail row. Proves `PRAGMA foreign_keys = ON` is in effect."""
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        created = await _create_post(
            repo,
            Post(kind="referral", owner_id=owner.id),
            make_referral_detail(description="doomed"),
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        await session.execute(
            text("DELETE FROM posts WHERE id = :pid").bindparams(
                bindparam("pid", type_=Uuid(as_uuid=True))
            ),
            {"pid": post_id},
        )
        await session.commit()

    async with db_test_session_manager() as session:
        detail_row = (
            (
                await session.execute(
                    select(ReferralDetail).filter(ReferralDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert detail_row is None


# --- Client referral kind ------------------------------------------------


async def test_create_post_persists_parent_and_referral_detail(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        post = Post(kind="referral", owner_id=owner.id)
        detail = make_referral_detail(description="needs placement")
        created = await _create_post(repo, post, detail)
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        post_row = (
            (await session.execute(select(Post).filter(Post.id == post_id)))
            .scalars()
            .first()
        )
        detail_row = (
            (
                await session.execute(
                    select(ReferralDetail).filter(ReferralDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert post_row is not None
        assert post_row.kind == "referral"
        assert detail_row is not None
        assert detail_row.description == "needs placement"


async def test_referral_persists_payment_paths_and_carriers(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """All four payment-path columns round-trip through the detail row
    (#1358 PR-e). The three booleans are NOT NULL with server-side
    default `false`; `insurance_carriers` is NOT NULL JSON with
    server-side default `[]`."""
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        in_network = await _create_post(
            repo,
            Post(kind="referral", owner_id=owner.id),
            make_referral_detail(
                description="cigna patient",
                accepts_in_network=True,
                accepts_out_of_network_superbill=False,
                accepts_private_pay=True,
                insurance_carriers=["cigna"],
            ),
        )
        private_pay_only = await _create_post(
            repo,
            Post(kind="referral", owner_id=owner.id),
            make_referral_detail(
                description="self-pay patient",
                accepts_in_network=False,
                accepts_out_of_network_superbill=False,
                accepts_private_pay=True,
                insurance_carriers=[],
            ),
        )
        await session.commit()
        in_id = in_network.id
        pp_id = private_pay_only.id

    async with db_test_session_manager() as session:
        in_row = (
            (
                await session.execute(
                    select(ReferralDetail).filter(ReferralDetail.post_id == in_id)
                )
            )
            .scalars()
            .first()
        )
        pp_row = (
            (
                await session.execute(
                    select(ReferralDetail).filter(ReferralDetail.post_id == pp_id)
                )
            )
            .scalars()
            .first()
        )
        assert in_row.accepts_in_network is True
        assert in_row.accepts_out_of_network_superbill is False
        assert in_row.accepts_private_pay is True
        assert in_row.insurance_carriers == ["cigna"]
        assert pp_row.accepts_in_network is False
        assert pp_row.accepts_out_of_network_superbill is False
        assert pp_row.accepts_private_pay is True
        assert pp_row.insurance_carriers == []


async def test_update_post_writes_to_referral_detail(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        created = await _create_post(
            repo,
            Post(kind="referral", owner_id=owner.id),
            make_referral_detail(description="orig"),
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        post = await repo.get_by_model_id(Post, post_id)
        # Detail fields live on the detail row; framework's handle_update
        # (B3) reads `kind_spec.detail_relationship` to pick the right
        # target. At the repo level we just patch the detail directly.
        await repo.patch(post.referral_detail, description="new description")
        await session.commit()

    async with db_test_session_manager() as session:
        detail_row = (
            (
                await session.execute(
                    select(ReferralDetail).filter(ReferralDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert detail_row.description == "new description"


async def test_delete_post_cascades_referral_detail(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Deleting a referral parent removes its detail row via FK CASCADE."""
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        created = await _create_post(
            repo,
            Post(kind="referral", owner_id=owner.id),
            make_referral_detail(description="doomed"),
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        post = await repo.get_by_model_id(Post, post_id)
        await repo.delete(post)
        await session.commit()

    async with db_test_session_manager() as session:
        post_row = (
            (await session.execute(select(Post).filter(Post.id == post_id)))
            .scalars()
            .first()
        )
        detail_row = (
            (
                await session.execute(
                    select(ReferralDetail).filter(ReferralDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert post_row is None
        assert detail_row is None


# --- Clinician availability kind ------------------------------------------


async def test_create_post_persists_parent_and_opening_detail(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner, clinician = await _seed_owner_and_clinician(
        db_test_session_manager, practice_name="Acme Health"
    )

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        post = Post(kind="clinician_opening", owner_id=owner.id)
        detail = make_opening_detail(clinician_id=clinician.id)
        created = await _create_post(repo, post, detail)
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        post_row = (
            (await session.execute(select(Post).filter(Post.id == post_id)))
            .scalars()
            .first()
        )
        detail_row = (
            (
                await session.execute(
                    select(OpeningDetail).filter(OpeningDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert post_row is not None
        assert post_row.kind == "clinician_opening"
        assert detail_row is not None
        # Practice name lives on the linked Clinician's primary ClinicianAffiliation's Organization.
        assert detail_row.clinician_id == clinician.id
        assert detail_row.clinician.org.name == "Acme Health"


async def test_create_post_round_trips_announcement_core(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """``description`` / ``schedule_text`` / ``subject`` persist + read
    back. ``referral_instructions`` / ``website`` moved to the
    affiliation in #1358 PR-f sub-3 and are no longer detail columns."""
    owner, clinician = await _seed_owner_and_clinician(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        detail = make_opening_detail(
            clinician_id=clinician.id,
            description="Lead pitch",
            schedule_text="Tues PM",
            subject="Spring cohort",
        )
        created = await _create_post(
            repo,
            Post(kind="clinician_opening", owner_id=owner.id),
            detail,
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        detail_row = (
            (
                await session.execute(
                    select(OpeningDetail).filter(OpeningDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert detail_row.description == "Lead pitch"
        assert detail_row.schedule_text == "Tues PM"
        assert detail_row.subject == "Spring cohort"


async def test_create_post_announcement_core_defaults_null(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Omitting the announcement-core scalars persists them as NULL —
    none of the surviving columns are NOT NULL beyond the FK + identity."""
    owner, clinician = await _seed_owner_and_clinician(
        db_test_session_manager, practice_name="No-extras"
    )

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        created = await _create_post(
            repo,
            Post(kind="clinician_opening", owner_id=owner.id),
            make_opening_detail(clinician_id=clinician.id),
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        detail_row = (
            (
                await session.execute(
                    select(OpeningDetail).filter(OpeningDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert detail_row.description is None
        assert detail_row.subject is None
        assert detail_row.schedule_text is None


async def test_update_post_writes_to_opening_detail(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner, clinician = await _seed_owner_and_clinician(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        created = await _create_post(
            repo,
            Post(kind="clinician_opening", owner_id=owner.id),
            make_opening_detail(clinician_id=clinician.id, description="orig"),
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        post = await repo.get_by_model_id(Post, post_id)
        # Practice-name lives on Clinician post-#448, so this round-trips a
        # remaining PA field (`description`) instead.
        await repo.patch(post.opening_detail, description="new description")
        await session.commit()

    async with db_test_session_manager() as session:
        detail_row = (
            (
                await session.execute(
                    select(OpeningDetail).filter(OpeningDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert detail_row.description == "new description"


async def test_delete_post_cascades_opening_detail(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Deleting a opening parent removes its detail row via
    FK CASCADE."""
    owner, clinician = await _seed_owner_and_clinician(
        db_test_session_manager, practice_name="Doomed"
    )

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        created = await _create_post(
            repo,
            Post(kind="clinician_opening", owner_id=owner.id),
            make_opening_detail(clinician_id=clinician.id),
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        post = await repo.get_by_model_id(Post, post_id)
        await repo.delete(post)
        await session.commit()

    async with db_test_session_manager() as session:
        post_row = (
            (await session.execute(select(Post).filter(Post.id == post_id)))
            .scalars()
            .first()
        )
        detail_row = (
            (
                await session.execute(
                    select(OpeningDetail).filter(OpeningDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert post_row is None
        assert detail_row is None


# --- Listing context (clinician_affiliation_id) -------------------------


async def test_opening_persists_clinician_affiliation_context(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`OpeningDetail.clinician_affiliation_id` round-trips — the FK to the
    affiliation the opening is offered under. The clinician factory builds
    a primary affiliation; we pin the opening to it."""
    owner, clinician = await _seed_owner_and_clinician(db_test_session_manager)
    affiliation_id = clinician.primary_clinician_affiliation.id

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        created = await _create_post(
            repo,
            Post(kind="clinician_opening", owner_id=owner.id),
            make_opening_detail(
                clinician_id=clinician.id, clinician_affiliation_id=affiliation_id
            ),
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        detail_row = (
            (
                await session.execute(
                    select(OpeningDetail).filter(OpeningDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert detail_row.clinician_affiliation_id == affiliation_id


async def test_opening_affiliation_context_defaults_null(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Omitting the context FK persists NULL — additive nullable column
    must not break a row that doesn't supply it."""
    owner, clinician = await _seed_owner_and_clinician(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        created = await _create_post(
            repo,
            Post(kind="clinician_opening", owner_id=owner.id),
            make_opening_detail(clinician_id=clinician.id),
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        detail_row = (
            (
                await session.execute(
                    select(OpeningDetail).filter(OpeningDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert detail_row.clinician_affiliation_id is None


async def test_referral_persists_clinician_affiliation_context(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`ReferralDetail.clinician_affiliation_id` round-trips — the FK to the
    affiliation the referring clinician is acting under."""
    owner, clinician = await _seed_owner_and_clinician(db_test_session_manager)
    affiliation_id = clinician.primary_clinician_affiliation.id

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        created = await _create_post(
            repo,
            Post(kind="referral", owner_id=owner.id),
            make_referral_detail(
                description="placement",
                referring_clinician_id=clinician.id,
                clinician_affiliation_id=affiliation_id,
            ),
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        detail_row = (
            (
                await session.execute(
                    select(ReferralDetail).filter(ReferralDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert detail_row.clinician_affiliation_id == affiliation_id


# --- Program availability kind ------------------------------------------


async def _seed_owner_and_program(db_test_session_manager, *, name: str = "RISE IOP"):
    """Seed a User + an Organization + a Program owned by the User
    (#541). Returns ``(owner, program)``. Program-availability detail
    rows point at a Program via ``program_id`` FK; persistence tests
    that flush a row need a real Program row in the DB to satisfy the
    FK."""
    owner = create_test_user(username=f"owner-{uuid.uuid4()}")
    org = make_organization_row(owner_id=owner.id, name=f"{name} Org")
    program = make_program(owner_id=owner.id, org_id=org.id, name=name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            session.add(org)
            session.add(program)
        await session.refresh(program)
    return owner, program


async def test_create_post_persists_parent_and_intake_detail(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner, program = await _seed_owner_and_program(
        db_test_session_manager, name="RISE IOP"
    )

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        post = Post(kind="program_intake", owner_id=owner.id)
        detail = make_intake_detail(program_id=program.id)
        created = await _create_post(repo, post, detail)
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        post_row = (
            (await session.execute(select(Post).filter(Post.id == post_id)))
            .scalars()
            .first()
        )
        detail_row = (
            (
                await session.execute(
                    select(IntakeDetail).filter(IntakeDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert post_row is not None
        assert post_row.kind == "program_intake"
        assert detail_row is not None
        assert detail_row.program_id == program.id
        # Dereferences the back_populated relationship so the template
        # `post.intake_detail.program.name` access path
        # is exercised at the ORM level here too.
        assert detail_row.program.name == "RISE IOP"


async def test_delete_post_cascades_intake_detail(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Deleting a intake parent removes its detail row via
    FK CASCADE — mirrors the PA cascade test."""
    owner, program = await _seed_owner_and_program(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        created = await _create_post(
            repo,
            Post(kind="program_intake", owner_id=owner.id),
            make_intake_detail(program_id=program.id),
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        post = await repo.get_by_model_id(Post, post_id)
        await repo.delete(post)
        await session.commit()

    async with db_test_session_manager() as session:
        detail_row = (
            (
                await session.execute(
                    select(IntakeDetail).filter(IntakeDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert detail_row is None


# --- Schema-level guard --------------------------------------------------


async def test_post_with_unknown_kind_violates_check_constraint(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The CHECK on `posts.kind` must reject any value outside the
    registered set. Guards against silently widening the kind universe
    by skipping a migration. The retired `note` kind is now in this
    rejected set."""
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        post = Post(kind="not_a_kind", owner_id=owner.id)
        with pytest.raises(IntegrityError):
            await _create_post(repo, post, make_referral_detail(description="d"))
            await session.commit()


async def test_retired_note_kind_violates_check_constraint(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`note` was removed from the registered kind set; inserts must fail."""
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        post = Post(kind="note", owner_id=owner.id)
        with pytest.raises(IntegrityError):
            await _create_post(repo, post, make_referral_detail(description="d"))
            await session.commit()
