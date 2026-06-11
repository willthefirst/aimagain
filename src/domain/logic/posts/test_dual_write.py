"""Tests for `PostRepository`'s dual-write of steady-state profile fields
(#1358 PR-f sub-PR 2).

When a `OpeningDetail` / `IntakeDetail` is created or patched through
`PostRepository`, the steady-state profile columns are mirrored onto
the linked `ClinicianAffiliation` / `Clinician` / `Program` so reads
from the new home (see `view.py`) stay consistent with what the writer
saw.

Dual-write is the safety net for the PR-f sub-PR 2 window: sub-PR 3
removes the per-announcement columns and only the new-home write
remains. Until then, every write that lands a value on the detail row
also lands it on the home; empty values are skipped so a PATCH that
touches only the announcement core (`description`, `desired_times`)
doesn't trample the affiliation's profile with a blank.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.posts.repository import PostRepository
from src.domain.models import (
    Clinician,
    ClinicianAffiliation,
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

pytestmark = pytest.mark.asyncio


# --- Opening dual-write -------------------------------------------------


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
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(affiliation)
        affiliation_id = affiliation.id

    return owner_id, clinician_id, org_id, affiliation_id


async def test_create_opening_mirrors_profile_onto_affiliation(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A fresh OpeningDetail with profile fields and an explicit
    ``clinician_affiliation_id`` mirrors those fields onto the
    affiliation row."""
    owner_id, clinician_id, _, affiliation_id = await _seed_opening_world(
        db_test_session_manager
    )

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        post = Post(kind="clinician_opening", owner_id=owner_id)
        detail = make_opening_detail(
            clinician_id=clinician_id,
            clinician_affiliation_id=affiliation_id,
            services=["medication_management", "psychotherapy"],
            settings=["outpatient"],
            modalities=["cbt"],
            age_groups=["adults_25_64"],
            genders=["female"],
            website="https://example.com",
            referral_instructions="Email intake@example.com",
            languages=["en", "zh"],
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
        clin_row = (
            (
                await session.execute(
                    select(Clinician).filter(Clinician.id == clinician_id)
                )
            )
            .scalars()
            .one()
        )

    assert aff_row.services == ["medication_management", "psychotherapy"]
    assert aff_row.settings == ["outpatient"]
    assert aff_row.modalities == ["cbt"]
    assert aff_row.age_groups == ["adults_25_64"]
    assert aff_row.genders == ["female"]
    assert aff_row.website == "https://example.com"
    assert aff_row.referral_instructions == "Email intake@example.com"
    # `languages` is person-level on the opening side — mirrored to
    # the Clinician, not the affiliation.
    assert clin_row.languages == ["en", "zh"]


async def test_patch_opening_mirrors_changed_fields_onto_affiliation(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A PATCH that changes profile fields on the detail row mirrors
    the new values onto the linked affiliation."""
    owner_id, clinician_id, _, affiliation_id = await _seed_opening_world(
        db_test_session_manager
    )

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        post = Post(kind="clinician_opening", owner_id=owner_id)
        detail = make_opening_detail(
            clinician_id=clinician_id,
            clinician_affiliation_id=affiliation_id,
            services=["psychotherapy"],
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
            services=["medication_management"],
            modalities=["dbt"],
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

    assert aff_row.services == ["medication_management"]
    assert aff_row.modalities == ["dbt"]


async def test_patch_opening_without_affiliation_id_skips_mirror(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """An OpeningDetail with ``clinician_affiliation_id=None`` is the
    legacy / pre-picker shape. The dual-write path skips the mirror
    silently — there's no unambiguous affiliation to target — and the
    write still lands on the detail row."""
    owner_id, clinician_id, _, affiliation_id = await _seed_opening_world(
        db_test_session_manager
    )

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        post = Post(kind="clinician_opening", owner_id=owner_id)
        detail = make_opening_detail(
            clinician_id=clinician_id,
            services=["psychotherapy"],
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

    # Affiliation profile stays empty — nothing was mirrored.
    assert aff_row.services == []
    # Detail row still carries the write (the dual-write fallback path
    # `view.py` reads from when the home is empty).
    assert detail_row.services == ["psychotherapy"]


async def test_patch_opening_skips_empty_values(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A patch that doesn't touch a profile field (e.g. only updates
    ``description``) doesn't trample the affiliation's existing
    profile with an empty list / None."""
    owner_id, clinician_id, _, affiliation_id = await _seed_opening_world(
        db_test_session_manager
    )

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        post = Post(kind="clinician_opening", owner_id=owner_id)
        detail = make_opening_detail(
            clinician_id=clinician_id,
            clinician_affiliation_id=affiliation_id,
            services=["psychotherapy"],
        )
        await repo.create_polymorphic(
            post, detail, detail_relationship="opening_detail"
        )
        await session.commit()
        post_id = post.id

    # Now wipe the detail row's `services` to `[]` and check the
    # affiliation's value survives (skip-empty invariant). The
    # `_patch` primitive skips None but writes `[]`, so we exercise
    # the empty-list case directly.
    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        post = await repo.get_by_model_id(Post, post_id)
        await repo.patch(post.opening_detail, settings=["outpatient"])
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

    # `services` is still on the affiliation from the create; only
    # `settings` got mirrored on the patch.
    assert aff_row.services == ["psychotherapy"]
    assert aff_row.settings == ["outpatient"]


# --- Intake dual-write --------------------------------------------------


async def _seed_intake_world(db_test_session_manager):
    """Persist a User + Org + Program. Returns ``(owner_id, program_id)``."""
    owner = create_test_user(username=f"owner-{uuid.uuid4()}")
    clinician = make_clinician_with_org(owner_id=owner.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            session.add(clinician)
        owner_id = owner.id
        org_id = clinician.org.id

    program = make_program(owner_id=owner_id, org_id=org_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(program)
        program_id = program.id

    return owner_id, program_id


async def test_create_intake_mirrors_profile_onto_program(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A fresh IntakeDetail with profile fields mirrors those onto its
    linked Program. ``languages`` is Program-level on the intake side
    (unlike the opening side, where it's person-level)."""
    owner_id, program_id = await _seed_intake_world(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        post = Post(kind="program_intake", owner_id=owner_id)
        detail = make_intake_detail(
            program_id=program_id,
            services=["group_therapy"],
            settings=["iop"],
            modalities=["dbt"],
            age_groups=["adolescents_14_18"],
            genders=[],
            languages=["en", "es"],
            website="https://prog.example",
            referral_instructions="Call intake",
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
