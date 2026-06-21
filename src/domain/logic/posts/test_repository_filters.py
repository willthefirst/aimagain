"""Tests for PostRepository.list_posts() filter dimensions.

Covers: geography, include_telehealth, level_of_care, modality, insurance,
age_group, language. Each dimension is tested in isolation, then
AND-combination and multi-value OR-within-field cases are pinned. Absent
params are verified to skip the WHERE clause (all posts returned).

After the opening remodel the opening became self-describing:
``age_group`` matches ``OpeningDetail.age_groups`` and ``include_telehealth``
matches ``OpeningDetail.session_format`` containing ``virtual``; the
``level_of_care`` / ``modality`` axes dropped off the opening side and now
match the intake-side ``Program`` only.
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
# level_of_care filter
# ---------------------------------------------------------------------------


async def _seed_program(db_test_session_manager, owner_id, org_id, **program_kwargs):
    """Persist a Program with a custom profile under ``org_id``. Returns
    the program id. After the opening remodel ``level_of_care`` /
    ``modality`` match the *intake* side only (``Program.settings`` /
    ``Program.modalities``); the opening side dropped both axes when its
    services collapsed onto the ``ReferralService`` vocabulary, so these
    filters are seeded on Programs, not affiliations."""
    name = program_kwargs.pop("name", f"P-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            program = make_program(
                owner_id=owner_id, org_id=org_id, name=name, **program_kwargs
            )
            session.add(program)
        return program.id


async def _seed_org(db_test_session_manager, owner_id):
    async with db_test_session_manager() as session:
        async with session.begin():
            org = make_organization_row(owner_id=owner_id)
            session.add(org)
        return org.id


async def test_level_of_care_matches_opening_settings(db_test_session_manager):
    """The opening side no longer models treatment settings (dropped when
    services collapsed onto the ``ReferralService`` vocabulary), so an
    opening never matches ``level_of_care`` — only intakes
    (``Program.settings``) do. Pin that an opening is excluded even when a
    matching intake exists."""
    owner = await _seed_user(db_test_session_manager)
    org_id = await _seed_org(db_test_session_manager, owner.id)
    match_pid = await _seed_program(
        db_test_session_manager, owner.id, org_id, settings=["php"]
    )

    async with db_test_session_manager() as session:
        async with session.begin():
            clinician = make_clinician_with_org(owner_id=owner.id)
            session.add(clinician)
        cid = clinician.id

    async with db_test_session_manager() as session:
        async with session.begin():
            intake_match = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=match_pid),
                "intake_detail",
            )
            # An opening exists but carries no settings axis at all — it
            # must not appear in a level_of_care-filtered result.
            opening = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=cid),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, level_of_care=["php"])
    ids = {p.id for p in results}
    assert intake_match.id in ids
    assert opening.id not in ids


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
    """Two level_of_care values → intakes matching either appear
    (intake-side ``Program.settings``)."""
    owner = await _seed_user(db_test_session_manager)
    org_id = await _seed_org(db_test_session_manager, owner.id)
    php_pid = await _seed_program(
        db_test_session_manager, owner.id, org_id, settings=["php"]
    )
    iop_pid = await _seed_program(
        db_test_session_manager, owner.id, org_id, settings=["iop"]
    )
    out_pid = await _seed_program(
        db_test_session_manager, owner.id, org_id, settings=["outpatient"]
    )

    async with db_test_session_manager() as session:
        async with session.begin():
            php_post = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=php_pid),
                "intake_detail",
            )
            iop_post = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=iop_pid),
                "intake_detail",
            )
            outpatient_post = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=out_pid),
                "intake_detail",
            )

    results = await _list(db_test_session_manager, level_of_care=["php", "iop"])
    ids = {p.id for p in results}
    assert php_post.id in ids
    assert iop_post.id in ids
    assert outpatient_post.id not in ids


async def test_level_of_care_absent_returns_all(db_test_session_manager):
    owner = await _seed_user(db_test_session_manager)
    org_id = await _seed_org(db_test_session_manager, owner.id)
    php_pid = await _seed_program(
        db_test_session_manager, owner.id, org_id, settings=["php"]
    )
    out_pid = await _seed_program(
        db_test_session_manager, owner.id, org_id, settings=["outpatient"]
    )

    async with db_test_session_manager() as session:
        async with session.begin():
            p1 = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=php_pid),
                "intake_detail",
            )
            p2 = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=out_pid),
                "intake_detail",
            )

    results = await _list(db_test_session_manager, level_of_care=None)
    ids = {p.id for p in results}
    assert p1.id in ids
    assert p2.id in ids


# ---------------------------------------------------------------------------
# modality filter
# ---------------------------------------------------------------------------


async def test_modality_excludes_openings(db_test_session_manager):
    """The opening side dropped ``modalities`` in the services collapse,
    so an opening never matches ``modality`` — only intakes
    (``Program.modalities``) do. Pin that the opening is excluded even
    when a matching intake exists."""
    owner = await _seed_user(db_test_session_manager)
    org_id = await _seed_org(db_test_session_manager, owner.id)
    match_pid = await _seed_program(
        db_test_session_manager, owner.id, org_id, modalities=["ifs"]
    )

    async with db_test_session_manager() as session:
        async with session.begin():
            clinician = make_clinician_with_org(owner_id=owner.id)
            session.add(clinician)
        cid = clinician.id

    async with db_test_session_manager() as session:
        async with session.begin():
            intake_match = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=match_pid),
                "intake_detail",
            )
            opening = await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=cid),
                "opening_detail",
            )

    results = await _list(db_test_session_manager, modality=["ifs"])
    ids = {p.id for p in results}
    assert intake_match.id in ids
    assert opening.id not in ids


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
    """Two modality values → intakes matching either appear
    (``Program.modalities``)."""
    owner = await _seed_user(db_test_session_manager)
    org_id = await _seed_org(db_test_session_manager, owner.id)
    emdr_pid = await _seed_program(
        db_test_session_manager, owner.id, org_id, modalities=["emdr"]
    )
    cbt_pid = await _seed_program(
        db_test_session_manager, owner.id, org_id, modalities=["cbt"]
    )
    dbt_pid = await _seed_program(
        db_test_session_manager, owner.id, org_id, modalities=["dbt"]
    )

    async with db_test_session_manager() as session:
        async with session.begin():
            emdr_post = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=emdr_pid),
                "intake_detail",
            )
            cbt_post = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=cbt_pid),
                "intake_detail",
            )
            dbt_post = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=dbt_pid),
                "intake_detail",
            )

    results = await _list(db_test_session_manager, modality=["emdr", "cbt"])
    ids = {p.id for p in results}
    assert emdr_post.id in ids
    assert cbt_post.id in ids
    assert dbt_post.id not in ids


async def test_modality_absent_returns_all(db_test_session_manager):
    owner = await _seed_user(db_test_session_manager)
    org_id = await _seed_org(db_test_session_manager, owner.id)
    a_pid = await _seed_program(
        db_test_session_manager, owner.id, org_id, modalities=["emdr"]
    )
    b_pid = await _seed_program(
        db_test_session_manager, owner.id, org_id, modalities=[]
    )

    async with db_test_session_manager() as session:
        async with session.begin():
            p1 = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=a_pid),
                "intake_detail",
            )
            p2 = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=b_pid),
                "intake_detail",
            )

    results = await _list(db_test_session_manager, modality=None)
    ids = {p.id for p in results}
    assert p1.id in ids
    assert p2.id in ids


async def test_modality_unknown_value_returns_no_match(db_test_session_manager):
    """Unknown modality value is silently ignored — no error, no match."""
    owner = await _seed_user(db_test_session_manager)
    org_id = await _seed_org(db_test_session_manager, owner.id)
    pid = await _seed_program(
        db_test_session_manager, owner.id, org_id, modalities=["emdr"]
    )

    async with db_test_session_manager() as session:
        async with session.begin():
            p = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=pid),
                "intake_detail",
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
# age_group filter — per-announcement on both seeking (ReferralDetail) and
# offering (OpeningDetail) sides; intake reads its steady-state Program.
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


# ---------------------------------------------------------------------------
# AND-combination across filters
# ---------------------------------------------------------------------------


async def test_and_combination_modality_and_level_of_care(db_test_session_manager):
    """An intake must satisfy BOTH active filters to appear (both axes are
    intake-side ``Program`` columns now)."""
    owner = await _seed_user(db_test_session_manager)
    org_id = await _seed_org(db_test_session_manager, owner.id)
    both_pid = await _seed_program(
        db_test_session_manager, owner.id, org_id, settings=["php"], modalities=["emdr"]
    )
    modality_only_pid = await _seed_program(
        db_test_session_manager,
        owner.id,
        org_id,
        settings=["outpatient"],
        modalities=["emdr"],
    )
    level_only_pid = await _seed_program(
        db_test_session_manager, owner.id, org_id, settings=["php"], modalities=["cbt"]
    )

    async with db_test_session_manager() as session:
        async with session.begin():
            both = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=both_pid),
                "intake_detail",
            )
            modality_only = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=modality_only_pid),
                "intake_detail",
            )
            _level_only = await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=level_only_pid),
                "intake_detail",
            )

    results = await _list(
        db_test_session_manager, modality=["emdr"], level_of_care=["php"]
    )
    ids = {p.id for p in results}
    assert both.id in ids
    assert modality_only.id not in ids


# ---------------------------------------------------------------------------
# Filter homes after the opening remodel: the opening's per-announcement
# profile (``age_groups`` / ``session_format``) lives on ``OpeningDetail``;
# its steady-state context (location / insurance) on ``ClinicianAffiliation``;
# its ``languages`` on the ``Clinician`` (person-level). The intake side
# reads its whole steady-state profile from ``Program``. This last test
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
