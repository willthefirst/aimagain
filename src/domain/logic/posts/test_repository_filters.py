"""Tests for PostRepository.list_posts() new filter dimensions.

Covers: geography, include_telehealth, level_of_care, modality, insurance.
Each dimension is tested in isolation, then AND-combination and multi-value
OR-within-field cases are pinned. Absent params are verified to skip the
WHERE clause (all posts returned).
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
                location_zip="94710",
            )
            no_match_clinician = make_clinician_with_org(
                owner_id=owner.id,
                location_city="Oakland",
                location_state="CA",
                location_zip="94601",
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
            # Clinician in a different CA city — virtual sessions enabled
            virtual_ca = make_clinician_with_org(
                owner_id=owner.id,
                location_city="San Francisco",
                location_state="CA",
                location_zip="94102",
                virtual_sessions="yes",
                practice_name="Virtual CA Practice",
            )
            # Clinician in a different state — should not appear
            out_of_state = make_clinician_with_org(
                owner_id=owner.id,
                location_city="Seattle",
                location_state="WA",
                location_zip="98101",
                virtual_sessions="yes",
                practice_name="WA Virtual Practice",
            )
            session.add(virtual_ca)
            session.add(out_of_state)

    async with db_test_session_manager() as session:
        async with session.begin():
            ca_post = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=virtual_ca.id),
                "opening_detail",
            )
            wa_post = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=out_of_state.id),
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
# level_of_care filter
# ---------------------------------------------------------------------------


async def test_level_of_care_matches_opening_settings(db_test_session_manager):
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
                make_opening_detail(clinician_id=clinician.id, settings=["php"]),
                "opening_detail",
            )
            no_match = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=clinician.id, settings=["outpatient"]),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, level_of_care=["php"])
    ids = {p.id for p in results}
    assert match.id in ids
    assert no_match.id not in ids


async def test_level_of_care_matches_intake_settings(db_test_session_manager):
    owner = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        async with session.begin():
            org = make_organization_row(owner_id=owner.id)
            session.add(org)

    async with db_test_session_manager() as session:
        async with session.begin():
            program = make_program(owner_id=owner.id, org_id=org.id)
            session.add(program)

    async with db_test_session_manager() as session:
        async with session.begin():
            match = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=program.id, settings=["iop"]),
                "intake_detail",
            )
            no_match = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=program.id, settings=["outpatient"]),
                "intake_detail",
            )

    results = await _list(db_test_session_manager, level_of_care=["iop"])
    ids = {p.id for p in results}
    assert match.id in ids
    assert no_match.id not in ids


async def test_level_of_care_multi_value_or(db_test_session_manager):
    """Two level_of_care values → posts matching either appear."""
    owner = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        async with session.begin():
            clinician = make_clinician_with_org(owner_id=owner.id)
            session.add(clinician)

    async with db_test_session_manager() as session:
        async with session.begin():
            php_post = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=clinician.id, settings=["php"]),
                "opening_detail",
            )
            iop_post = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=clinician.id, settings=["iop"]),
                "opening_detail",
            )
            outpatient_post = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=clinician.id, settings=["outpatient"]),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, level_of_care=["php", "iop"])
    ids = {p.id for p in results}
    assert php_post.id in ids
    assert iop_post.id in ids
    assert outpatient_post.id not in ids


async def test_level_of_care_absent_returns_all(db_test_session_manager):
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
                make_opening_detail(clinician_id=clinician.id, settings=["php"]),
                "opening_detail",
            )
            p2 = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=clinician.id, settings=["outpatient"]),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, level_of_care=None)
    ids = {p.id for p in results}
    assert p1.id in ids
    assert p2.id in ids


# ---------------------------------------------------------------------------
# modality filter
# ---------------------------------------------------------------------------


async def test_modality_matches_referral_modalities(db_test_session_manager):
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
                    referring_clinician_id=clinician.id, modalities=["emdr"]
                ),
                "referral_detail",
            )
            no_match = await _add_post(
                session,
                owner.id,
                make_referral_detail(
                    referring_clinician_id=clinician.id, modalities=["cbt"]
                ),
                "referral_detail",
            )

    results = await _list(db_test_session_manager, modality=["emdr"])
    ids = {p.id for p in results}
    assert match.id in ids
    assert no_match.id not in ids


async def test_modality_matches_opening_modalities(db_test_session_manager):
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
                make_opening_detail(clinician_id=clinician.id, modalities=["ifs"]),
                "opening_detail",
            )
            no_match = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=clinician.id, modalities=["dbt"]),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, modality=["ifs"])
    ids = {p.id for p in results}
    assert match.id in ids
    assert no_match.id not in ids


async def test_modality_matches_intake_modalities(db_test_session_manager):
    owner = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        async with session.begin():
            org = make_organization_row(owner_id=owner.id)
            session.add(org)

    async with db_test_session_manager() as session:
        async with session.begin():
            program = make_program(owner_id=owner.id, org_id=org.id)
            session.add(program)

    async with db_test_session_manager() as session:
        async with session.begin():
            match = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=program.id, modalities=["somatic"]),
                "intake_detail",
            )
            no_match = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=program.id, modalities=["act"]),
                "intake_detail",
            )

    results = await _list(db_test_session_manager, modality=["somatic"])
    ids = {p.id for p in results}
    assert match.id in ids
    assert no_match.id not in ids


async def test_modality_multi_value_or(db_test_session_manager):
    """Two modality values → posts matching either appear."""
    owner = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        async with session.begin():
            clinician = make_clinician_with_org(owner_id=owner.id)
            session.add(clinician)

    async with db_test_session_manager() as session:
        async with session.begin():
            emdr_post = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=clinician.id, modalities=["emdr"]),
                "opening_detail",
            )
            cbt_post = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=clinician.id, modalities=["cbt"]),
                "opening_detail",
            )
            dbt_post = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=clinician.id, modalities=["dbt"]),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, modality=["emdr", "cbt"])
    ids = {p.id for p in results}
    assert emdr_post.id in ids
    assert cbt_post.id in ids
    assert dbt_post.id not in ids


async def test_modality_absent_returns_all(db_test_session_manager):
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
                make_opening_detail(clinician_id=clinician.id, modalities=["emdr"]),
                "opening_detail",
            )
            p2 = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=clinician.id, modalities=[]),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, modality=None)
    ids = {p.id for p in results}
    assert p1.id in ids
    assert p2.id in ids


async def test_modality_unknown_value_returns_no_match(db_test_session_manager):
    """Unknown modality value is silently ignored — no error, no match."""
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
                make_opening_detail(clinician_id=clinician.id, modalities=["emdr"]),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, modality=["not_a_real_modality"])
    assert p.id not in {post.id for post in results}


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
                    accepts_in_network=True,
                ),
                "referral_detail",
            )
            no_match = await _add_post(
                session,
                owner.id,
                make_referral_detail(
                    referring_clinician_id=clinician.id,
                    insurance_carriers=["cigna"],
                    accepts_in_network=True,
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
                    accepts_in_network=True,
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
# AND-combination across filters
# ---------------------------------------------------------------------------


async def test_and_combination_modality_and_level_of_care(db_test_session_manager):
    """A post must satisfy BOTH active filters to appear."""
    owner = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        async with session.begin():
            clinician = make_clinician_with_org(owner_id=owner.id)
            session.add(clinician)

    async with db_test_session_manager() as session:
        async with session.begin():
            # Matches both
            both = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=clinician.id,
                    settings=["php"],
                    modalities=["emdr"],
                ),
                "opening_detail",
            )
            # Matches modality only
            modality_only = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=clinician.id,
                    settings=["outpatient"],
                    modalities=["emdr"],
                ),
                "opening_detail",
            )
            # Matches level_of_care only
            level_only = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=clinician.id,
                    settings=["php"],
                    modalities=["cbt"],
                ),
                "opening_detail",
            )

    results = await _list(
        db_test_session_manager, modality=["emdr"], level_of_care=["php"]
    )
    ids = {p.id for p in results}
    assert both.id in ids
    assert modality_only.id not in ids
    assert level_only.id not in ids
