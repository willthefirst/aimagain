"""Tests for PostRepository.list_posts() filter dimensions.

Covers: session_format, services, insurance, age_group, language. Each
dimension is tested in isolation, then multi-value OR-within-field cases
are pinned. Absent params are verified to skip the WHERE clause (all posts
returned).

Every post kind is self-describing on its own detail row, so the
per-announcement filters read across all three: ``age_group`` and
``services`` match ``ReferralDetail`` / ``OpeningDetail`` / ``IntakeDetail``;
``session_format`` matches ReferralDetail + OpeningDetail (intakes have no
delivery axis). The old free-text ``geography`` + ``include_telehealth``
flag folded into the structured ``state`` / ``city`` / ``session_format``
filters; ``level_of_care`` / ``modality`` were removed when settings /
modalities collapsed onto the single ``services`` axis.
"""

from __future__ import annotations

import uuid

import pytest

from src.domain.logic.posts.repository import PostRepository
from src.domain.models import Post
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


# ---------------------------------------------------------------------------
# Shared seed helpers
# ---------------------------------------------------------------------------


async def _seed_user(db_test_session_manager):
    user = create_test_user(username=f"filter-owner-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
    return user


async def _add_post(session, owner_id, detail, detail_relationship: str) -> Post:
    """Persist a Post + detail row and return the flushed Post."""
    kind_map = {
        "referral_detail": "referral",
        "opening_detail": "clinician_opening",
        "intake_detail": "program_intake",
    }
    post = Post(kind=kind_map[detail_relationship], owner_id=owner_id)
    repo = BaseRepository(session)
    return await repo.create_polymorphic(
        post, detail, detail_relationship=detail_relationship
    )


async def _list(db_test_session_manager, **kwargs) -> list[Post]:
    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        return list(await repo.list_posts(**kwargs))


# ---------------------------------------------------------------------------
# Shared intake-seed helpers (a Program needs an Org parent; the intake's
# own profile — services / age_groups / genders / cost — lives on its
# IntakeDetail, not the Program).
# ---------------------------------------------------------------------------


async def _seed_org(db_test_session_manager, owner_id):
    async with db_test_session_manager() as session:
        async with session.begin():
            org = make_organization_row(owner_id=owner_id)
            session.add(org)
        return org.id


async def _seed_program(db_test_session_manager, owner_id, org_id, **program_kwargs):
    """Persist a Program under ``org_id`` and return its id. The Program
    now carries only steady-state context (name / state_preference /
    languages / website / referral_instructions); the per-announcement
    profile lives on each ``IntakeDetail``."""
    name = program_kwargs.pop("name", f"P-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            program = make_program(
                owner_id=owner_id, org_id=org_id, name=name, **program_kwargs
            )
            session.add(program)
        return program.id


# ---------------------------------------------------------------------------
# session_format filter (replaces the old free-text geography + telehealth)
# ---------------------------------------------------------------------------


async def test_session_format_matches_referral_and_opening(db_test_session_manager):
    """``session_format`` matches the per-announcement delivery format on
    ReferralDetail + OpeningDetail (both carry the list); intakes have no
    session-format axis, so they never match."""
    owner = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            clinician = make_clinician_with_org(owner_id=owner.id)
            session.add(clinician)

    async with db_test_session_manager() as session:
        async with session.begin():
            ref_match = await _add_post(
                session,
                owner.id,
                make_referral_detail(
                    referring_clinician_id=clinician.id, session_format=["virtual"]
                ),
                "referral_detail",
            )
            ref_no = await _add_post(
                session,
                owner.id,
                make_referral_detail(
                    referring_clinician_id=clinician.id, session_format=["in_person"]
                ),
                "referral_detail",
            )
            open_match = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=clinician.id, session_format=["in_person", "virtual"]
                ),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, session_format=["virtual"])
    ids = {p.id for p in results}
    assert ref_match.id in ids
    assert open_match.id in ids
    assert ref_no.id not in ids


async def test_session_format_absent_returns_all(db_test_session_manager):
    owner = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            clinician = make_clinician_with_org(owner_id=owner.id)
            session.add(clinician)
    async with db_test_session_manager() as session:
        async with session.begin():
            p = await _add_post(
                session,
                owner.id,
                make_referral_detail(referring_clinician_id=clinician.id),
                "referral_detail",
            )
    results = await _list(db_test_session_manager)
    assert p.id in {post.id for post in results}


# ---------------------------------------------------------------------------
# services filter — the unified "what care" axis across every kind
# ---------------------------------------------------------------------------


async def test_services_matches_across_all_kinds(db_test_session_manager):
    """``services`` matches the ``ReferralService`` token on each kind's own
    detail row — ReferralDetail, OpeningDetail, and IntakeDetail."""
    owner = await _seed_user(db_test_session_manager)
    org_id = await _seed_org(db_test_session_manager, owner.id)
    pid = await _seed_program(db_test_session_manager, owner.id, org_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            clinician = make_clinician_with_org(owner_id=owner.id)
            session.add(clinician)

    async with db_test_session_manager() as session:
        async with session.begin():
            ref_match = await _add_post(
                session,
                owner.id,
                make_referral_detail(
                    referring_clinician_id=clinician.id,
                    services=["medication_management"],
                ),
                "referral_detail",
            )
            open_match = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=clinician.id, services=["medication_management"]
                ),
                "opening_detail",
            )
            intake_match = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=pid, services=["medication_management"]),
                "intake_detail",
            )
            no_match = await _add_post(
                session,
                owner.id,
                make_referral_detail(
                    referring_clinician_id=clinician.id, services=["therapy_group"]
                ),
                "referral_detail",
            )

    results = await _list(db_test_session_manager, services=["medication_management"])
    ids = {p.id for p in results}
    assert {ref_match.id, open_match.id, intake_match.id} <= ids
    assert no_match.id not in ids


# ---------------------------------------------------------------------------
# insurance filter
# ---------------------------------------------------------------------------


async def test_insurance_matches_referral_carrier(db_test_session_manager):
    owner = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        async with session.begin():
            clinician = make_clinician_with_org(owner_id=owner.id)
            session.add(clinician)

    async with db_test_session_manager() as session:
        async with session.begin():
            match = await _add_post(
                session,
                owner.id,
                make_referral_detail(
                    referring_clinician_id=clinician.id,
                    insurance_carriers=["aetna"],
                ),
                "referral_detail",
            )
            no_match = await _add_post(
                session,
                owner.id,
                make_referral_detail(
                    referring_clinician_id=clinician.id,
                    insurance_carriers=["cigna"],
                ),
                "referral_detail",
            )

    results = await _list(db_test_session_manager, insurance=["aetna"])
    ids = {p.id for p in results}
    assert match.id in ids
    assert no_match.id not in ids


async def test_insurance_matches_opening_in_network_carriers(db_test_session_manager):
    owner = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        async with session.begin():
            match_clinician = make_clinician_with_org(
                owner_id=owner.id,
                in_network_carriers=["aetna"],
                practice_name="Aetna Practice",
            )
            no_match_clinician = make_clinician_with_org(
                owner_id=owner.id,
                in_network_carriers=["cigna"],
                practice_name="Cigna Practice",
            )
            session.add(match_clinician)
            session.add(no_match_clinician)

    async with db_test_session_manager() as session:
        async with session.begin():
            match = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=match_clinician.id),
                "opening_detail",
            )
            no_match = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=no_match_clinician.id),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, insurance=["aetna"])
    ids = {p.id for p in results}
    assert match.id in ids
    assert no_match.id not in ids


async def test_insurance_absent_returns_all(db_test_session_manager):
    owner = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        async with session.begin():
            clinician = make_clinician_with_org(
                owner_id=owner.id, in_network_carriers=["aetna"]
            )
            session.add(clinician)

    async with db_test_session_manager() as session:
        async with session.begin():
            p1 = await _add_post(
                session,
                owner.id,
                make_referral_detail(
                    referring_clinician_id=clinician.id,
                    insurance_carriers=["aetna"],
                ),
                "referral_detail",
            )
            p2 = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=clinician.id),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, insurance=None)
    ids = {p.id for p in results}
    assert p1.id in ids
    assert p2.id in ids


# ---------------------------------------------------------------------------
# age_group filter — per-announcement on ALL three detail rows now:
# ReferralDetail (the single client), OpeningDetail + IntakeDetail (the
# cohort the announcement serves). The intake no longer reads age_groups
# from its linked Program.
# ---------------------------------------------------------------------------


async def test_age_group_matches_opening_age_groups(db_test_session_manager):
    """After the opening remodel ``age_group`` matches the opening's own
    ``OpeningDetail.age_groups`` (the cohort it serves), not the linked
    affiliation."""
    owner = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        async with session.begin():
            clinician = make_clinician_with_org(owner_id=owner.id)
            session.add(clinician)
        cid = clinician.id

    async with db_test_session_manager() as session:
        async with session.begin():
            match = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=cid, age_groups=["adolescents_14_18", "adults_25_64"]
                ),
                "opening_detail",
            )
            no_match = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=cid, age_groups=["older_adults_65_plus"]
                ),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, age_group=["adolescents_14_18"])
    ids = {p.id for p in results}
    assert match.id in ids
    assert no_match.id not in ids


async def test_age_group_matches_referral_age_groups(db_test_session_manager):
    """The seeking side keeps matching ``ReferralDetail.age_groups``
    (the single client's bucket)."""
    owner = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        async with session.begin():
            clinician = make_clinician_with_org(owner_id=owner.id)
            session.add(clinician)

    async with db_test_session_manager() as session:
        async with session.begin():
            match = await _add_post(
                session,
                owner.id,
                make_referral_detail(
                    referring_clinician_id=clinician.id, age_groups=["children_6_10"]
                ),
                "referral_detail",
            )
            no_match = await _add_post(
                session,
                owner.id,
                make_referral_detail(
                    referring_clinician_id=clinician.id, age_groups=["adults_25_64"]
                ),
                "referral_detail",
            )

    results = await _list(db_test_session_manager, age_group=["children_6_10"])
    ids = {p.id for p in results}
    assert match.id in ids
    assert no_match.id not in ids


async def test_age_group_matches_intake_age_groups(db_test_session_manager):
    """After the program-intake remodel ``age_group`` matches the intake's
    own ``IntakeDetail.age_groups`` (the cohort it serves), not the linked
    Program (which no longer carries the column)."""
    owner = await _seed_user(db_test_session_manager)
    org_id = await _seed_org(db_test_session_manager, owner.id)
    pid = await _seed_program(db_test_session_manager, owner.id, org_id)

    async with db_test_session_manager() as session:
        async with session.begin():
            match = await _add_post(
                session,
                owner.id,
                make_intake_detail(
                    program_id=pid,
                    age_groups=["adolescents_14_18", "adults_25_64"],
                ),
                "intake_detail",
            )
            no_match = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=pid, age_groups=["older_adults_65_plus"]),
                "intake_detail",
            )

    results = await _list(db_test_session_manager, age_group=["adolescents_14_18"])
    ids = {p.id for p in results}
    assert match.id in ids
    assert no_match.id not in ids


# ---------------------------------------------------------------------------
# Filter homes after the program-intake remodel: every kind's
# per-announcement profile (``age_groups`` / ``genders`` / ``services`` /
# ``cost`` — and ``session_format`` for the opening) lives on its own
# detail row. Steady-state context still lives off the detail row: the
# opening's location / insurance on ``ClinicianAffiliation`` and its
# ``languages`` on the ``Clinician`` (person-level); the intake's
# ``languages`` on the linked ``Program`` (program-level). This last test
# pins the ``languages`` ↔ ``Clinician`` link specifically, since
# ``languages`` lives on the person — not the affiliation — for openings.
# ---------------------------------------------------------------------------


async def test_language_matches_clinician_languages(db_test_session_manager):
    """Opening side: ``languages`` lives on ``Clinician`` (person-
    level), distinct from the other steady-state fields which live on
    the affiliation."""
    owner = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            clinician = make_clinician_with_org(owner_id=owner.id, languages=["zh"])
            session.add(clinician)
        clinician_id = clinician.id

    async with db_test_session_manager() as session:
        async with session.begin():
            match = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=clinician_id),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, language=["zh"])
    ids = {p.id for p in results}
    assert match.id in ids
