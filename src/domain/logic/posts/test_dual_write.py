"""Tests for the thin OpeningDetail / IntakeDetail shape after #1358
PR-f sub-3.

Sub-PR 1 (#1380) added steady-state profile columns on
``ClinicianAffiliation`` / ``Clinician`` / ``Program`` and backfilled
them. Sub-PR 2 (#1386) flipped reads and dual-wrote any value landing
on the per-announcement detail row onto the steady-state home. This
sub-PR (#3) drops the per-announcement columns entirely; the dual-
write is gone and so is the fallback-to-detail read in the view layer.

A later remodel then reversed the split for the opening's
*per-announcement* dimensions: ``OpeningDetail`` regained
``services`` / ``age_groups`` / ``genders`` and gained
``session_format`` / ``services_other_text`` / ``cost`` — the opening
is self-describing now. ``IntakeDetail`` was untouched and stays thin.

These tests pin the current contract:

  * ``OpeningDetail`` carries the announcement core, the context FKs,
    and the self-describing profile; only the truly steady-state
    columns (``settings`` / ``modalities`` / ``languages`` /
    ``website`` / ``referral_instructions``) stay off it.
  * ``IntakeDetail`` exposes no steady-state profile columns at all —
    the thin shape carries only the announcement core plus the
    context FK.
  * Writing an opening's profile to its detail row does **not** touch
    the linked affiliation's steady-state context (and creating an
    ``IntakeDetail`` does not overwrite the linked Program's profile).

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

# The opening remodel reversed the #1358 split for the *per-announcement*
# dimensions: `services` / `age_groups` / `genders` are back on
# `OpeningDetail` (it's self-describing now), alongside the new
# `session_format` / `services_other_text` / `cost`. Only the truly
# steady-state columns stay off the opening row.
_REMOVED_COLUMNS_OPENING = (
    "settings",
    "modalities",
    "languages",
    "website",
    "referral_instructions",
)
# IntakeDetail is unchanged by the opening remodel — it stays thin, with
# its whole steady-state profile (services / settings / modalities /
# age_groups / genders / languages / website / referral_instructions) on
# the linked `Program`.
_REMOVED_COLUMNS_INTAKE = (
    "services",
    "settings",
    "modalities",
    "age_groups",
    "genders",
    "languages",
    "website",
    "referral_instructions",
)


def test_opening_detail_has_no_steady_state_columns():
    """Only the truly steady-state columns stayed off ``OpeningDetail``
    (``settings`` / ``modalities`` dropped entirely; ``languages`` /
    ``website`` / ``referral_instructions`` live on the affiliation /
    clinician). The per-announcement dimensions (``services`` /
    ``age_groups`` / ``genders``) came back when the opening became
    self-describing — they are asserted present in
    ``test_opening_detail_thin_shape``."""
    column_names = {c.name for c in OpeningDetail.__table__.columns}
    for col in _REMOVED_COLUMNS_OPENING:
        assert (
            col not in column_names
        ), f"OpeningDetail still carries removed column {col!r}"


def test_intake_detail_has_no_steady_state_columns():
    """Mirror invariant for IntakeDetail → Program."""
    column_names = {c.name for c in IntakeDetail.__table__.columns}
    for col in _REMOVED_COLUMNS_INTAKE:
        assert (
            col not in column_names
        ), f"IntakeDetail still carries removed steady-state column {col!r}"


def test_opening_detail_thin_shape():
    """OpeningDetail's columns are the announcement core + context FKs +
    the self-describing announcement profile (`session_format` /
    `services` / `services_other_text` / `age_groups` / `genders` /
    `cost`). The opening reverses the #1358 split for these
    per-announcement dimensions while leaving steady-state context
    (location, insurance, how-to-refer, languages) on the affiliation /
    clinician."""
    expected = {
        "post_id",
        "clinician_id",
        "clinician_affiliation_id",
        "schedule_text",
        "description",
        "session_format",
        "services",
        "services_other_text",
        "age_groups",
        "genders",
        "cost",
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
    about session-bound state across the per-step session boundaries.

    The affiliation carries only steady-state *context* now — the
    per-announcement profile (services / age_groups / genders /
    session_format / cost) moved back onto the opening, so it's set on
    the ``OpeningDetail`` by the callers, not here."""
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
        in_network_carriers=["aetna"],
        sliding_scale=True,
        website="https://aff.example",
        referral_instructions="Email intake@aff.example",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(affiliation)
        affiliation_id = affiliation.id

    return owner_id, clinician_id, org_id, affiliation_id


@pytest.mark.asyncio
async def test_create_opening_stores_profile_on_detail_not_affiliation(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The opening is self-describing: its announcement profile
    (session_format / services / age_groups / genders / cost) lands on
    the ``OpeningDetail`` row, while the linked affiliation's
    steady-state *context* (insurance, how-to-refer) is left untouched."""
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
            session_format=["virtual"],
            services=["psychotherapy"],
            age_groups=["adults_25_64", "adolescents_14_18"],
            genders=["female"],
            cost="$150/session",
        )
        await repo.create_polymorphic(
            post, detail, detail_relationship="opening_detail"
        )
        await session.commit()
        post_id = post.id

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

    # Announcement profile is on the opening detail row.
    assert detail_row.session_format == ["virtual"]
    assert detail_row.services == ["psychotherapy"]
    assert detail_row.age_groups == ["adults_25_64", "adolescents_14_18"]
    assert detail_row.genders == ["female"]
    assert detail_row.cost == "$150/session"
    # Affiliation steady-state context untouched.
    assert aff_row.in_network_carriers == ["aetna"]
    assert aff_row.sliding_scale is True
    assert aff_row.website == "https://aff.example"
    assert aff_row.referral_instructions == "Email intake@aff.example"


@pytest.mark.asyncio
async def test_patch_opening_profile_does_not_touch_affiliation(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """PATCH-ing the opening's announcement profile (description,
    schedule, services, cost) on the detail row does not propagate into
    the affiliation's steady-state context — they're separate homes."""
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
            services=["medication_management"],
            cost="$200",
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

    # Detail picks up the announcement change.
    assert detail_row.description == "Updated copy"
    assert detail_row.schedule_text == "Tues PM"
    assert detail_row.services == ["medication_management"]
    assert detail_row.cost == "$200"
    # Affiliation context is unchanged.
    assert aff_row.in_network_carriers == ["aetna"]
    assert aff_row.website == "https://aff.example"


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
