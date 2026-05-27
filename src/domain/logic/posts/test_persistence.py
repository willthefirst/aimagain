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


async def test_referral_persists_network_preference_and_carrier(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Both insurance fields round-trip through the detail row.
    `network_preference` is required (CHECK against NETWORK_PREFERENCES);
    `insurance_carrier` is nullable — null is the expected shape when the
    referrer says 'no preference' / patient is self-pay."""
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        with_carrier = await _create_post(
            repo,
            Post(kind="referral", owner_id=owner.id),
            make_referral_detail(
                description="cigna patient",
                network_preference="in_network_preferred",
                insurance_carrier="cigna",
            ),
        )
        no_carrier = await _create_post(
            repo,
            Post(kind="referral", owner_id=owner.id),
            make_referral_detail(
                description="self-pay patient",
                network_preference="no_preference",
                insurance_carrier=None,
            ),
        )
        await session.commit()
        with_id = with_carrier.id
        no_id = no_carrier.id

    async with db_test_session_manager() as session:
        with_row = (
            (
                await session.execute(
                    select(ReferralDetail).filter(ReferralDetail.post_id == with_id)
                )
            )
            .scalars()
            .first()
        )
        no_row = (
            (
                await session.execute(
                    select(ReferralDetail).filter(ReferralDetail.post_id == no_id)
                )
            )
            .scalars()
            .first()
        )
        assert with_row.network_preference == "in_network_preferred"
        assert with_row.insurance_carrier == "cigna"
        assert no_row.network_preference == "no_preference"
        assert no_row.insurance_carrier is None


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
        # Practice name lives on the linked Clinician's primary Affiliation's Organization.
        assert detail_row.clinician_id == clinician.id
        assert detail_row.clinician.org.name == "Acme Health"


async def test_create_post_round_trips_free_text_fields(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`description`, `referral_instructions`, `website` persist + read back."""
    owner, clinician = await _seed_owner_and_clinician(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        detail = make_opening_detail(
            clinician_id=clinician.id,
            description="Lead pitch",
            referral_instructions="Email the coordinator",
            website="example.com",
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
        assert detail_row.referral_instructions == "Email the coordinator"
        assert detail_row.website == "example.com"


async def test_create_post_free_text_fields_default_null(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Omitting the three new fields persists them as NULL — additive
    columns must not break a row that doesn't supply them."""
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
        assert detail_row.referral_instructions is None
        assert detail_row.website is None


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
