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


async def _seed_clinician_with_affiliation(
    db_test_session_manager, owner_id, **affiliation_kwargs
):
    """Persist a Clinician + a ClinicianAffiliation with custom profile
    values. Returns ``(clinician_id, affiliation_id)``."""
    from src.domain.models import ClinicianAffiliation

    async with db_test_session_manager() as session:
        async with session.begin():
            clinician = make_clinician_with_org(owner_id=owner_id)
            session.add(clinician)
        clinician_id = clinician.id
        org_id = clinician.org.id

    async with db_test_session_manager() as session:
        async with session.begin():
            affiliation = ClinicianAffiliation(
                clinician_id=clinician_id,
                org_id=org_id,
                **affiliation_kwargs,
            )
            session.add(affiliation)
        affiliation_id = affiliation.id
    return clinician_id, affiliation_id


async def test_level_of_care_matches_opening_settings(db_test_session_manager):
    """Opening-side settings live on ``ClinicianAffiliation`` after
    #1358 PR-f sub-3."""
    owner = await _seed_user(db_test_session_manager)
    match_cid, match_aid = await _seed_clinician_with_affiliation(
        db_test_session_manager, owner.id, settings=["php"]
    )
    no_cid, no_aid = await _seed_clinician_with_affiliation(
        db_test_session_manager, owner.id, settings=["outpatient"]
    )

    async with db_test_session_manager() as session:
        async with session.begin():
            match = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=match_cid, clinician_affiliation_id=match_aid
                ),
                "opening_detail",
            )
            no_match = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=no_cid, clinician_affiliation_id=no_aid
                ),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, level_of_care=["php"])
    ids = {p.id for p in results}
    assert match.id in ids
    assert no_match.id not in ids


async def test_level_of_care_matches_intake_settings(db_test_session_manager):
    """Intake-side settings live on ``Program``."""
    owner = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        async with session.begin():
            org = make_organization_row(owner_id=owner.id)
            session.add(org)
        org_id = org.id

    async with db_test_session_manager() as session:
        async with session.begin():
            match_prog = make_program(
                owner_id=owner.id, org_id=org_id, name="P1", settings=["iop"]
            )
            no_prog = make_program(
                owner_id=owner.id, org_id=org_id, name="P2", settings=["outpatient"]
            )
            session.add(match_prog)
            session.add(no_prog)
        match_pid = match_prog.id
        no_pid = no_prog.id

    async with db_test_session_manager() as session:
        async with session.begin():
            match = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=match_pid),
                "intake_detail",
            )
            no_match = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=no_pid),
                "intake_detail",
            )

    results = await _list(db_test_session_manager, level_of_care=["iop"])
    ids = {p.id for p in results}
    assert match.id in ids
    assert no_match.id not in ids


async def test_level_of_care_multi_value_or(db_test_session_manager):
    """Two level_of_care values → posts matching either appear."""
    owner = await _seed_user(db_test_session_manager)
    php_cid, php_aid = await _seed_clinician_with_affiliation(
        db_test_session_manager, owner.id, settings=["php"]
    )
    iop_cid, iop_aid = await _seed_clinician_with_affiliation(
        db_test_session_manager, owner.id, settings=["iop"]
    )
    out_cid, out_aid = await _seed_clinician_with_affiliation(
        db_test_session_manager, owner.id, settings=["outpatient"]
    )

    async with db_test_session_manager() as session:
        async with session.begin():
            php_post = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=php_cid, clinician_affiliation_id=php_aid
                ),
                "opening_detail",
            )
            iop_post = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=iop_cid, clinician_affiliation_id=iop_aid
                ),
                "opening_detail",
            )
            outpatient_post = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=out_cid, clinician_affiliation_id=out_aid
                ),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, level_of_care=["php", "iop"])
    ids = {p.id for p in results}
    assert php_post.id in ids
    assert iop_post.id in ids
    assert outpatient_post.id not in ids


async def test_level_of_care_absent_returns_all(db_test_session_manager):
    owner = await _seed_user(db_test_session_manager)
    php_cid, php_aid = await _seed_clinician_with_affiliation(
        db_test_session_manager, owner.id, settings=["php"]
    )
    out_cid, out_aid = await _seed_clinician_with_affiliation(
        db_test_session_manager, owner.id, settings=["outpatient"]
    )

    async with db_test_session_manager() as session:
        async with session.begin():
            p1 = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=php_cid, clinician_affiliation_id=php_aid
                ),
                "opening_detail",
            )
            p2 = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=out_cid, clinician_affiliation_id=out_aid
                ),
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
    """Opening-side modalities live on ``ClinicianAffiliation``."""
    owner = await _seed_user(db_test_session_manager)
    match_cid, match_aid = await _seed_clinician_with_affiliation(
        db_test_session_manager, owner.id, modalities=["ifs"]
    )
    no_cid, no_aid = await _seed_clinician_with_affiliation(
        db_test_session_manager, owner.id, modalities=["dbt"]
    )

    async with db_test_session_manager() as session:
        async with session.begin():
            match = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=match_cid, clinician_affiliation_id=match_aid
                ),
                "opening_detail",
            )
            no_match = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=no_cid, clinician_affiliation_id=no_aid
                ),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, modality=["ifs"])
    ids = {p.id for p in results}
    assert match.id in ids
    assert no_match.id not in ids


async def test_modality_matches_intake_modalities(db_test_session_manager):
    """Intake-side modalities live on ``Program``."""
    owner = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        async with session.begin():
            org = make_organization_row(owner_id=owner.id)
            session.add(org)
        org_id = org.id

    async with db_test_session_manager() as session:
        async with session.begin():
            match_prog = make_program(
                owner_id=owner.id, org_id=org_id, name="P1", modalities=["somatic"]
            )
            no_prog = make_program(
                owner_id=owner.id, org_id=org_id, name="P2", modalities=["act"]
            )
            session.add(match_prog)
            session.add(no_prog)
        match_pid = match_prog.id
        no_pid = no_prog.id

    async with db_test_session_manager() as session:
        async with session.begin():
            match = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=match_pid),
                "intake_detail",
            )
            no_match = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=no_pid),
                "intake_detail",
            )

    results = await _list(db_test_session_manager, modality=["somatic"])
    ids = {p.id for p in results}
    assert match.id in ids
    assert no_match.id not in ids


async def test_modality_multi_value_or(db_test_session_manager):
    """Two modality values → posts matching either appear."""
    owner = await _seed_user(db_test_session_manager)
    emdr_cid, emdr_aid = await _seed_clinician_with_affiliation(
        db_test_session_manager, owner.id, modalities=["emdr"]
    )
    cbt_cid, cbt_aid = await _seed_clinician_with_affiliation(
        db_test_session_manager, owner.id, modalities=["cbt"]
    )
    dbt_cid, dbt_aid = await _seed_clinician_with_affiliation(
        db_test_session_manager, owner.id, modalities=["dbt"]
    )

    async with db_test_session_manager() as session:
        async with session.begin():
            emdr_post = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=emdr_cid, clinician_affiliation_id=emdr_aid
                ),
                "opening_detail",
            )
            cbt_post = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=cbt_cid, clinician_affiliation_id=cbt_aid
                ),
                "opening_detail",
            )
            dbt_post = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=dbt_cid, clinician_affiliation_id=dbt_aid
                ),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, modality=["emdr", "cbt"])
    ids = {p.id for p in results}
    assert emdr_post.id in ids
    assert cbt_post.id in ids
    assert dbt_post.id not in ids


async def test_modality_absent_returns_all(db_test_session_manager):
    owner = await _seed_user(db_test_session_manager)
    a_cid, a_aid = await _seed_clinician_with_affiliation(
        db_test_session_manager, owner.id, modalities=["emdr"]
    )
    b_cid, b_aid = await _seed_clinician_with_affiliation(
        db_test_session_manager, owner.id, modalities=[]
    )

    async with db_test_session_manager() as session:
        async with session.begin():
            p1 = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=a_cid, clinician_affiliation_id=a_aid),
                "opening_detail",
            )
            p2 = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=b_cid, clinician_affiliation_id=b_aid),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, modality=None)
    ids = {p.id for p in results}
    assert p1.id in ids
    assert p2.id in ids


async def test_modality_unknown_value_returns_no_match(db_test_session_manager):
    """Unknown modality value is silently ignored — no error, no match."""
    owner = await _seed_user(db_test_session_manager)
    cid, aid = await _seed_clinician_with_affiliation(
        db_test_session_manager, owner.id, modalities=["emdr"]
    )

    async with db_test_session_manager() as session:
        async with session.begin():
            p = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=cid, clinician_affiliation_id=aid),
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
    both_cid, both_aid = await _seed_clinician_with_affiliation(
        db_test_session_manager, owner.id, settings=["php"], modalities=["emdr"]
    )
    modality_only_cid, modality_only_aid = await _seed_clinician_with_affiliation(
        db_test_session_manager, owner.id, settings=["outpatient"], modalities=["emdr"]
    )
    level_only_cid, level_only_aid = await _seed_clinician_with_affiliation(
        db_test_session_manager, owner.id, settings=["php"], modalities=["cbt"]
    )

    async with db_test_session_manager() as session:
        async with session.begin():
            both = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=both_cid, clinician_affiliation_id=both_aid
                ),
                "opening_detail",
            )
            modality_only = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=modality_only_cid,
                    clinician_affiliation_id=modality_only_aid,
                ),
                "opening_detail",
            )
            _level_only = await _add_post(
                session,
                owner.id,
                make_opening_detail(
                    clinician_id=level_only_cid,
                    clinician_affiliation_id=level_only_aid,
                ),
                "opening_detail",
            )

    results = await _list(
        db_test_session_manager, modality=["emdr"], level_of_care=["php"]
    )
    ids = {p.id for p in results}
    assert both.id in ids
    assert modality_only.id not in ids


# ---------------------------------------------------------------------------
# #1358 PR-f sub-3: the opening-side steady-state home is
# ``ClinicianAffiliation`` (and ``Clinician`` for ``languages``); the
# intake-side home is ``Program``. The general filter tests above already
# pin reads from the new home — the legacy "when detail empty" cases
# went away with sub-PR 3 because the detail-row columns no longer exist.
# This last test pins the ``languages`` ↔ ``Clinician`` link specifically,
# since ``languages`` lives on the person — not the affiliation — for
# openings only.
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
