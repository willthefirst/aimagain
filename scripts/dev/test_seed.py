"""Tests for `scripts/dev/seed.py`.

Three invariants matter beyond "the script ran":
  - On a fresh DB, the seed functions insert the full fixture set and
    populate each parent `Post` with its detail row in the same flush.
    A regression where the parent is committed without the detail
    would 500 every read view that joins the detail in.
  - Re-running is a no-op. The idempotency keys
    (opening: `kind + owner_id + provider_id` (with
    Provider matched by `(owner_id, org_id)` and Org by `name`);
    referral: `kind + owner_id + description`) keep `dev seed`
    safe to run repeatedly during development.
  - `created_at` is varied via the per-fixture `days_ago` field so the
    listings feed renders a spread of dates, not a wall of identical
    timestamps. A regression where the `_shift_created_at` override
    silently became a no-op would collapse the feed back to one date.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from scripts.dev import seed
from src.domain.models import (
    OpeningDetail,
    Organization,
    Post,
    Provider,
    ProviderCertification,
    ProviderEducation,
    ProviderLicensure,
    ReferralDetail,
)
from tests.fixtures import async_test_sessionmaker
from tests.helpers import create_test_user

# Counts derive from the fixture lists themselves so adding/removing a
# fixture is a one-line edit in `seed.py` without test-count drift.
_PA_COUNT = len(seed.FIXTURE_OPENING)
_CR_COUNT = len(seed.FIXTURE_REFERRAL)


@pytest.fixture(autouse=True)
def patch_session_maker(monkeypatch):
    """Point the seed script at the in-memory test database."""
    monkeypatch.setattr(seed, "async_session_maker", async_test_sessionmaker)


async def _insert_all_fixture_users() -> None:
    """Persist all fixture users so the post seeders have valid owners
    to FK against. Each test inserts the full set so individual tests
    don't need to know which users own which fixtures."""
    async with async_test_sessionmaker() as session:
        async with session.begin():
            for fixture in seed.FIXTURE_USERS:
                session.add(
                    create_test_user(
                        email=fixture["email"], username=fixture["username"]
                    )
                )


async def _all_pa_posts() -> list[Post]:
    async with async_test_sessionmaker() as session:
        result = await session.execute(
            select(Post).where(Post.kind == "clinician_opening")
        )
        return list(result.scalars().all())


async def _all_cr_posts() -> list[Post]:
    async with async_test_sessionmaker() as session:
        result = await session.execute(select(Post).where(Post.kind == "referral"))
        return list(result.scalars().all())


# --- opening ------------------------------------------------


async def test_inserts_all_pa_posts_on_fresh_db(db_test_session_manager):
    await _insert_all_fixture_users()

    created, skipped = await seed.seed_opening()

    assert (created, skipped) == (_PA_COUNT, 0)
    posts = await _all_pa_posts()
    assert len(posts) == _PA_COUNT


async def test_each_pa_post_has_populated_detail_relationship(db_test_session_manager):
    await _insert_all_fixture_users()

    await seed.seed_opening()

    async with async_test_sessionmaker() as session:
        result = await session.execute(
            select(OpeningDetail).join(Post, Post.id == OpeningDetail.post_id)
        )
        details = list(result.scalars().all())

    # Practice name lives on the linked Provider's Organization (#524).
    practice_names = {d.provider.org.name for d in details}
    expected = {f["provider"]["practice_name"] for f in seed.FIXTURE_OPENING}
    assert practice_names == expected


async def test_pa_rerun_is_idempotent(db_test_session_manager):
    await _insert_all_fixture_users()

    first = await seed.seed_opening()
    second = await seed.seed_opening()

    assert first == (_PA_COUNT, 0)
    assert second == (0, _PA_COUNT)
    assert len(await _all_pa_posts()) == _PA_COUNT


async def test_pa_skips_when_owner_missing(db_test_session_manager, capsys):
    # No fixture users seeded — every fixture row should be skipped.
    created, skipped = await seed.seed_opening()

    assert created == 0
    assert skipped == _PA_COUNT
    assert await _all_pa_posts() == []


# --- referral ------------------------------------------------------


async def test_inserts_all_cr_posts_on_fresh_db(db_test_session_manager):
    await _insert_all_fixture_users()

    created, skipped = await seed.seed_referral()

    assert (created, skipped) == (_CR_COUNT, 0)
    posts = await _all_cr_posts()
    assert len(posts) == _CR_COUNT


async def test_each_cr_post_has_populated_detail_relationship(db_test_session_manager):
    await _insert_all_fixture_users()

    await seed.seed_referral()

    async with async_test_sessionmaker() as session:
        result = await session.execute(
            select(ReferralDetail).join(Post, Post.id == ReferralDetail.post_id)
        )
        details = list(result.scalars().all())

    descriptions = {d.description for d in details}
    expected = {f["detail"]["description"] for f in seed.FIXTURE_REFERRAL}
    assert descriptions == expected


async def test_cr_rerun_is_idempotent(db_test_session_manager):
    await _insert_all_fixture_users()

    first = await seed.seed_referral()
    second = await seed.seed_referral()

    assert first == (_CR_COUNT, 0)
    assert second == (0, _CR_COUNT)
    assert len(await _all_cr_posts()) == _CR_COUNT


async def test_cr_skips_when_owner_missing(db_test_session_manager):
    created, skipped = await seed.seed_referral()

    assert created == 0
    assert skipped == _CR_COUNT
    assert await _all_cr_posts() == []


# --- created_at variance --------------------------------------------------


# --- org type variety + hierarchy -----------------------------------------


async def test_seed_opening_creates_orgs_with_declared_types(db_test_session_manager):
    """Each provider fixture declares an `org_type` (default
    `solo_practice`). The seed honors it on Org create so the directory
    isn't a wall of identical solo-practice rows."""
    await _insert_all_fixture_users()
    await seed.seed_opening()

    async with async_test_sessionmaker() as session:
        result = await session.execute(select(Organization))
        orgs_by_name = {o.name: o for o in result.scalars().all()}

    expected = {
        f["provider"]["practice_name"]: f["provider"]["org_type"]
        for f in seed.FIXTURE_OPENING
    }
    for name, want_type in expected.items():
        assert name in orgs_by_name, f"Org '{name}' was not seeded"
        assert (
            orgs_by_name[name].type == want_type
        ), f"Org '{name}' got type {orgs_by_name[name].type!r}, expected {want_type!r}"
    # Coverage: the seeded set spans more than just `solo_practice`.
    seen_types = {o.type for o in orgs_by_name.values()}
    assert len(seen_types) >= 3, f"Expected variety, got: {seen_types}"


async def test_seed_standalone_orgs_creates_health_system_parent(
    db_test_session_manager,
):
    """`seed_standalone_orgs()` populates the hierarchy roots that
    Provider fixtures attach to via `parent_org_name`. Specifically the
    Children's Health Council health_system row that RISE IOP at CHC
    nests under."""
    await _insert_all_fixture_users()

    created, skipped = await seed.seed_standalone_orgs()

    assert created == len(seed.FIXTURE_STANDALONE_ORGS)
    assert skipped == 0
    async with async_test_sessionmaker() as session:
        result = await session.execute(
            select(Organization).where(Organization.name == "Children's Health Council")
        )
        chc = result.scalar_one()
    assert chc.type == "health_system"
    # Roots are their own root.
    assert chc.root_org_id == chc.id
    assert chc.parent_org_id is None


async def test_provider_fixtures_have_no_placeholder_locations():
    """Pins #596: no provider fixture renders the `(telehealth), CA 00000`
    sentinel that read like a placeholder bug on the providers list.
    Practices that only deliver care virtually still declare a real
    business city + ZIP; the (in_person, virtual) flags carry the
    telehealth-only signal at the wire layer."""
    for fixture in seed.FIXTURE_OPENING:
        provider = fixture["provider"]
        assert provider["location_city"] != "(telehealth)", (
            f"{provider['practice_name']!r} still uses the (telehealth) "
            "city sentinel — pick a real city; the virtual_sessions flag "
            "carries the telehealth signal."
        )
        assert provider["location_zip"] != "00000", (
            f"{provider['practice_name']!r} still uses the 00000 ZIP "
            "sentinel — pick a plausible ZIP for the practice's "
            "business address."
        )


async def test_seed_opening_attaches_clinic_to_health_system_parent(
    db_test_session_manager,
):
    """RISE IOP at CHC declares `parent_org_name=Children's Health Council`.
    After `seed_standalone_orgs()` + `seed_opening()`, the child's
    `parent_org_id` + `root_org_id` reflect the parent."""
    await _insert_all_fixture_users()
    await seed.seed_standalone_orgs()
    await seed.seed_opening()

    async with async_test_sessionmaker() as session:
        parent = (
            await session.execute(
                select(Organization).where(
                    Organization.name == "Children's Health Council"
                )
            )
        ).scalar_one()
        child = (
            await session.execute(
                select(Organization).where(Organization.name == "RISE IOP at CHC")
            )
        ).scalar_one()
    assert child.parent_org_id == parent.id
    assert child.root_org_id == parent.id


# --- credentials ----------------------------------------------------------


async def test_seed_credentials_inserts_rows_attached_to_provider(
    db_test_session_manager,
):
    """`seed_credentials()` populates each Provider's licensures /
    educations / certifications. Pins that at least one of each kind
    landed and that they correctly attach to the seeded Provider."""
    await _insert_all_fixture_users()
    await seed.seed_opening()

    created, _ = await seed.seed_credentials()
    assert created > 0

    async with async_test_sessionmaker() as session:
        # `Provider.org_id` moved to `Affiliation.org_id` in #635 PR B —
        # join through the 1:1 `affiliations.provider_id` link.
        from src.domain.models import Affiliation

        provider = (
            await session.execute(
                select(Provider)
                .join(Affiliation, Affiliation.provider_id == Provider.id)
                .join(Organization, Organization.id == Affiliation.org_id)
                .where(Organization.name == "Lakeside Therapy Collective")
            )
        ).scalar_one()
        lic_count = (
            (
                await session.execute(
                    select(ProviderLicensure).where(
                        ProviderLicensure.clinician_id == provider.clinician_id
                    )
                )
            )
            .scalars()
            .all()
        )
        edu_count = (
            (
                await session.execute(
                    select(ProviderEducation).where(
                        ProviderEducation.clinician_id == provider.clinician_id
                    )
                )
            )
            .scalars()
            .all()
        )
        cert_count = (
            (
                await session.execute(
                    select(ProviderCertification).where(
                        ProviderCertification.clinician_id == provider.clinician_id
                    )
                )
            )
            .scalars()
            .all()
        )
    # Lakeside fixture: 2 licensures (multi-state), 1 education, 2 certs.
    assert len(lic_count) == 2
    assert {l.issuing_state for l in lic_count} == {"CA", "NV"}
    assert len(edu_count) == 1
    assert len(cert_count) == 2


async def test_seed_credentials_rerun_is_idempotent(db_test_session_manager):
    """Re-running `seed_credentials()` doesn't duplicate rows."""
    await _insert_all_fixture_users()
    await seed.seed_opening()

    first_created, first_skipped = await seed.seed_credentials()
    second_created, second_skipped = await seed.seed_credentials()

    assert first_created > 0
    assert second_created == 0
    assert second_skipped == first_created


async def test_seed_credentials_skips_when_provider_missing(db_test_session_manager):
    """No Providers seeded → every credential fixture is skipped, no
    error raised."""
    await _insert_all_fixture_users()
    # Deliberately skip seed_opening — no Providers to attach to.

    created, skipped = await seed.seed_credentials()

    assert created == 0
    assert skipped == len(seed.FIXTURE_CREDENTIALS)


async def test_seed_spreads_created_at_across_days(db_test_session_manager):
    """`days_ago` overrides the server-defaulted `created_at` so the
    listings feed shows a date range. Pins that the override actually
    takes effect — a regression collapsing all posts to `now()` would
    fail here."""
    await _insert_all_fixture_users()
    await seed.seed_opening()
    await seed.seed_referral()

    posts = await _all_pa_posts() + await _all_cr_posts()
    timestamps = {p.created_at.date() for p in posts}
    # Every fixture declares its own `days_ago`; even one duplicate is
    # fine, but we expect substantial spread. Assert at least 5 distinct
    # dates across the combined fixture set so a "all-set-to-now"
    # regression can't sneak through.
    assert len(timestamps) >= 5
    # And: the oldest post should be at least 90 days back, proving
    # the spread covers a meaningful window (today's "older posts"
    # filter exists for a reason).
    now = datetime.now(timezone.utc).date()
    oldest = min(timestamps)
    assert (now - oldest).days >= 90
