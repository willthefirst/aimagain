"""Tests for PostRepository.list_posts() filter dimensions.

Covers: geography, include_telehealth, insurance, age_group, language.
Each dimension is tested in isolation, then multi-value OR-within-field
cases are pinned. Absent params are verified to skip the WHERE clause
(all posts returned).

After the program-intake remodel every post kind is self-describing on
its own detail row: ``age_group`` matches ``ReferralDetail.age_groups``,
``OpeningDetail.age_groups``, AND ``IntakeDetail.age_groups`` (no longer
the linked ``Program``); ``include_telehealth`` matches
``OpeningDetail.session_format`` containing ``virtual``. The
``level_of_care`` / ``modality`` axes were removed entirely — no post
kind models treatment settings or modalities anymore (services collapsed
onto the single ``ReferralService`` "what care" axis across all three
kinds).
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
# geography filter
# ---------------------------------------------------------------------------


async def test_geography_matches_referral_city(db_test_session_manager):
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
                    location_city="Portland",
                    location_state="OR",
                ),
                "referral_detail",
            )
            no_match = await _add_post(
                session,
                owner.id,
                make_referral_detail(
                    referring_clinician_id=clinician.id,
                    location_city="Denver",
                    location_state="CO",
                ),
                "referral_detail",
            )

    results = await _list(db_test_session_manager, geography="Portland")
    ids = {p.id for p in results}
    assert match.id in ids
    assert no_match.id not in ids


async def test_geography_matches_referral_state(db_test_session_manager):
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
                    location_city="Eugene",
                    location_state="OR",
                ),
                "referral_detail",
            )
            no_match = await _add_post(
                session,
                owner.id,
                make_referral_detail(
                    referring_clinician_id=clinician.id,
                    location_city="Boise",
                    location_state="ID",
                ),
                "referral_detail",
            )

    results = await _list(db_test_session_manager, geography="OR")
    ids = {p.id for p in results}
    assert match.id in ids
    assert no_match.id not in ids


async def test_geography_matches_opening_affiliation_city(db_test_session_manager):
    owner = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        async with session.begin():
            match_clinician = make_clinician_with_org(
                owner_id=owner.id,
                location_city="Berkeley",
                location_state="CA",
            )
            no_match_clinician = make_clinician_with_org(
                owner_id=owner.id,
                location_city="Oakland",
                location_state="CA",
                practice_name="Other Practice",
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

    results = await _list(db_test_session_manager, geography="Berkeley")
    ids = {p.id for p in results}
    assert match.id in ids
    assert no_match.id not in ids


async def test_geography_absent_returns_all(db_test_session_manager):
    owner = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        async with session.begin():
            clinician = make_clinician_with_org(owner_id=owner.id)
            session.add(clinician)

    async with db_test_session_manager() as session:
        async with session.begin():
            p1 = await _add_post(
                session,
                owner.id,
                make_referral_detail(
                    referring_clinician_id=clinician.id, location_city="Austin"
                ),
                "referral_detail",
            )
            p2 = await _add_post(
                session,
                owner.id,
                make_referral_detail(
                    referring_clinician_id=clinician.id, location_city="Miami"
                ),
                "referral_detail",
            )

    results = await _list(db_test_session_manager, geography=None)
    ids = {p.id for p in results}
    assert p1.id in ids
    assert p2.id in ids


# ---------------------------------------------------------------------------
# include_telehealth + geography
# ---------------------------------------------------------------------------


async def test_include_telehealth_expands_geography_to_virtual_ca(
    db_test_session_manager,
):
    """A virtual/CA opening appears when geography='CA' + include_telehealth='1',
    even though the affiliation city doesn't match the search term."""
    owner = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        async with session.begin():
            # Clinician in a different CA city. Telehealth is now a
            # per-announcement attribute (the opening's `session_format`),
            # not a clinician/affiliation column — set below on the post.
            virtual_ca = make_clinician_with_org(
                owner_id=owner.id,
                location_city="San Francisco",
                location_state="CA",
                practice_name="Virtual CA Practice",
            )
            # Clinician in a different state — should not appear
            out_of_state = make_clinician_with_org(
                owner_id=owner.id,
                location_city="Seattle",
                location_state="WA",
                practice_name="WA Virtual Practice",
            )
            session.add(virtual_ca)
            session.add(out_of_state)

    async with db_test_session_manager() as session:
        async with session.begin():
            ca_post = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=virtual_ca.id, session_format=["virtual"]
                ),
                "opening_detail",
            )
            wa_post = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=out_of_state.id, session_format=["virtual"]
                ),
                "opening_detail",
            )

    # geography="CA" matches location_state; include_telehealth also adds
    # the virtual+CA clause — the CA clinician matches on both paths.
    results = await _list(
        db_test_session_manager, geography="CA", include_telehealth="1"
    )
    ids = {p.id for p in results}
    assert ca_post.id in ids
    assert wa_post.id not in ids


async def test_include_telehealth_alone_adds_no_constraint(db_test_session_manager):
    """include_telehealth with no geography param returns all posts."""
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

    results = await _list(db_test_session_manager, include_telehealth="1")
    assert p.id in {post.id for post in results}


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
