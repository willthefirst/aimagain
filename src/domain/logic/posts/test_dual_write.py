"""Tests for the thin OpeningDetail / IntakeDetail shape after #1358
PR-f sub-3.

Sub-PR 1 (#1380) added steady-state profile columns on
``ClinicianAffiliation`` / ``Clinician`` / ``Program`` and backfilled
them. Sub-PR 2 (#1386) flipped reads and dual-wrote any value landing
on the per-announcement detail row onto the steady-state home. This
sub-PR (#3) drops the per-announcement columns entirely; the dual-
write is gone and so is the fallback-to-detail read in the view layer.

These tests pin the post-sub-3 contract:

  * ``OpeningDetail`` / ``IntakeDetail`` no longer expose the steady-
    state profile columns at all (attribute access on a fresh row
    raises). The thin shape carries only the announcement core plus
    the context FK(s).
  * Creating an ``OpeningDetail`` / ``IntakeDetail`` does **not**
    overwrite the linked affiliation / clinician / program's profile —
    the steady-state home is the canonical source and is edited
    through its own pages.

(The file kept its ``test_dual_write.py`` name so PR-f sub-PR 2's
tests can be archived in `git log`; the dual-write window closed with
this PR.)
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.posts.repository import PostRepository
from src.domain.models import (
    Clinician,
    ClinicianAffiliation,
    IntakeDetail,
    OpeningDetail,
    Post,
    Program,
)
from tests.helpers import (
    create_test_user,
    make_clinician_with_org,
    make_intake_detail,
    make_opening_detail,
    make_program,
)

_REMOVED_COLUMNS_OPENING = (
    "services",
    "settings",
    "modalities",
    "age_groups",
    "genders",
    "languages",
    "website",
    "referral_instructions",
)
_REMOVED_COLUMNS_INTAKE = _REMOVED_COLUMNS_OPENING  # intake also lost languages


def test_opening_detail_has_no_steady_state_columns():
    """Every steady-state profile column moved off ``OpeningDetail``
    onto ``ClinicianAffiliation`` (and ``languages`` onto ``Clinician``)
    in sub-PR 3. The columns themselves are gone — not just unused."""
    column_names = {c.name for c in OpeningDetail.__table__.columns}
    for col in _REMOVED_COLUMNS_OPENING:
        assert (
            col not in column_names
        ), f"OpeningDetail still carries removed steady-state column {col!r}"


def test_intake_detail_has_no_steady_state_columns():
    """Mirror invariant for IntakeDetail → Program."""
    column_names = {c.name for c in IntakeDetail.__table__.columns}
    for col in _REMOVED_COLUMNS_INTAKE:
        assert (
            col not in column_names
        ), f"IntakeDetail still carries removed steady-state column {col!r}"


def test_opening_detail_thin_shape():
    """OpeningDetail's surviving columns are exactly the announcement
    core plus the context FKs."""
    expected = {
        "post_id",
        "clinician_id",
        "clinician_affiliation_id",
        "schedule_text",
        "description",
    }
    assert {c.name for c in OpeningDetail.__table__.columns} == expected


def test_intake_detail_thin_shape():
    """IntakeDetail's surviving columns are exactly the announcement
    core plus the context FK."""
    expected = {
        "post_id",
        "program_id",
        "schedule_text",
        "description",
    }
    assert {c.name for c in IntakeDetail.__table__.columns} == expected


# --- Steady-state homes are untouched on detail-row create ---------------


async def _seed_opening_world(db_test_session_manager):
    """Persist a User + Clinician + Org + ClinicianAffiliation linked
    to that clinician. Returns ``(owner_id, clinician_id, org_id,
    affiliation_id)`` — plain UUIDs so callers don't have to worry
    about session-bound state across the per-step session boundaries."""
    owner = create_test_user(username=f"owner-{uuid.uuid4()}")
    clinician = make_clinician_with_org(owner_id=owner.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            session.add(clinician)
        clinician_id = clinician.id
        org_id = clinician.org.id
        owner_id = owner.id

    affiliation = ClinicianAffiliation(
        clinician_id=clinician_id,
        org_id=org_id,
        services=["psychotherapy"],
        settings=["outpatient"],
        modalities=["cbt"],
        age_groups=["adults_25_64"],
        genders=["female"],
        website="https://aff.example",
        referral_instructions="Email intake@aff.example",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(affiliation)
        affiliation_id = affiliation.id

    return owner_id, clinician_id, org_id, affiliation_id


@pytest.mark.asyncio
async def test_create_opening_does_not_touch_affiliation_profile(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The thin OpeningDetail carries no steady-state profile. Creating
    one must NOT overwrite the affiliation's standing profile — the
    steady-state home is the canonical source after sub-PR 3."""
    owner_id, clinician_id, _, affiliation_id = await _seed_opening_world(
        db_test_session_manager
    )

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        post = Post(kind="clinician_opening", owner_id=owner_id)
        detail = make_opening_detail(
            clinician_id=clinician_id,
            clinician_affiliation_id=affiliation_id,
            description="Caseload opening this fall.",
        )
        await repo.create_polymorphic(
            post, detail, detail_relationship="opening_detail"
        )
        await session.commit()

    async with db_test_session_manager() as session:
        aff_row = (
            (
                await session.execute(
                    select(ClinicianAffiliation).filter(
                        ClinicianAffiliation.id == affiliation_id
                    )
                )
            )
            .scalars()
            .one()
        )

    # Affiliation profile untouched — the announcement carried no
    # steady-state fields, so nothing to mirror and nothing to overwrite.
    assert aff_row.services == ["psychotherapy"]
    assert aff_row.settings == ["outpatient"]
    assert aff_row.modalities == ["cbt"]
    assert aff_row.age_groups == ["adults_25_64"]
    assert aff_row.genders == ["female"]
    assert aff_row.website == "https://aff.example"
    assert aff_row.referral_instructions == "Email intake@aff.example"


@pytest.mark.asyncio
async def test_patch_opening_announcement_core_does_not_touch_affiliation(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """PATCH-ing announcement-core fields (description, schedule) on the
    detail row does not propagate into the affiliation's profile —
    there's no longer any mirror path."""
    owner_id, clinician_id, _, affiliation_id = await _seed_opening_world(
        db_test_session_manager
    )

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        post = Post(kind="clinician_opening", owner_id=owner_id)
        detail = make_opening_detail(
            clinician_id=clinician_id,
            clinician_affiliation_id=affiliation_id,
        )
        await repo.create_polymorphic(
            post, detail, detail_relationship="opening_detail"
        )
        await session.commit()
        post_id = post.id

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        post = await repo.get_by_model_id(Post, post_id)
        await repo.patch(
            post.opening_detail,
            description="Updated copy",
            schedule_text="Tues PM",
        )
        await session.commit()

    async with db_test_session_manager() as session:
        aff_row = (
            (
                await session.execute(
                    select(ClinicianAffiliation).filter(
                        ClinicianAffiliation.id == affiliation_id
                    )
                )
            )
            .scalars()
            .one()
        )
        detail_row = (
            (
                await session.execute(
                    select(OpeningDetail).filter(OpeningDetail.post_id == post_id)
                )
            )
            .scalars()
            .one()
        )

    # Detail picks up the announcement-core change.
    assert detail_row.description == "Updated copy"
    assert detail_row.schedule_text == "Tues PM"
    # Affiliation profile is unchanged — no dual-write any more.
    assert aff_row.services == ["psychotherapy"]
    assert aff_row.modalities == ["cbt"]


async def _seed_intake_world(db_test_session_manager):
    """Persist a User + Org + Program with a populated profile."""
    owner = create_test_user(username=f"owner-{uuid.uuid4()}")
    clinician = make_clinician_with_org(owner_id=owner.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            session.add(clinician)
        owner_id = owner.id
        org_id = clinician.org.id

    program = make_program(
        owner_id=owner_id,
        org_id=org_id,
        services=["group_therapy"],
        settings=["iop"],
        modalities=["dbt"],
        age_groups=["adolescents_14_18"],
        languages=["en", "es"],
        website="https://prog.example",
        referral_instructions="Call intake",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(program)
        program_id = program.id

    return owner_id, program_id


@pytest.mark.asyncio
async def test_create_intake_does_not_touch_program_profile(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Creating an IntakeDetail does not overwrite the Program's
    steady-state profile — the Program is the canonical source."""
    owner_id, program_id = await _seed_intake_world(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        post = Post(kind="program_intake", owner_id=owner_id)
        detail = make_intake_detail(
            program_id=program_id,
            description="Fall cohort intake opening.",
        )
        await repo.create_polymorphic(post, detail, detail_relationship="intake_detail")
        await session.commit()

    async with db_test_session_manager() as session:
        prog_row = (
            (await session.execute(select(Program).filter(Program.id == program_id)))
            .scalars()
            .one()
        )

    assert prog_row.services == ["group_therapy"]
    assert prog_row.settings == ["iop"]
    assert prog_row.modalities == ["dbt"]
    assert prog_row.age_groups == ["adolescents_14_18"]
    assert prog_row.languages == ["en", "es"]
    assert prog_row.website == "https://prog.example"
    assert prog_row.referral_instructions == "Call intake"


# Reference unused imports to satisfy linters when the seeded worlds
# above already pin `Clinician` indirectly through the helpers.
_ = Clinician
