"""Tests for `scripts/dev/seed.py`.

Three invariants matter beyond "the script ran":
  - On a fresh DB, the seed functions insert the full fixture set and
    populate each parent `Post` with its detail row in the same flush.
    A regression where the parent is committed without the detail
    would 500 every read view that joins the detail in.
  - Re-running is a no-op. The idempotency keys
    (provider_availability: `kind + owner_id + provider_id` (with
    Provider matched by `(owner_id, org_id)` and Org by `name`);
    client_referral: `kind + owner_id + description`) keep `dev seed`
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
from src.domain.models import ClientReferralDetail, Post, ProviderAvailabilityDetail
from tests.fixtures import async_test_sessionmaker
from tests.helpers import create_test_user

# Counts derive from the fixture lists themselves so adding/removing a
# fixture is a one-line edit in `seed.py` without test-count drift.
_PA_COUNT = len(seed.FIXTURE_PROVIDER_AVAILABILITY)
_CR_COUNT = len(seed.FIXTURE_CLIENT_REFERRAL)


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
            select(Post).where(Post.kind == "provider_availability")
        )
        return list(result.scalars().all())


async def _all_cr_posts() -> list[Post]:
    async with async_test_sessionmaker() as session:
        result = await session.execute(
            select(Post).where(Post.kind == "client_referral")
        )
        return list(result.scalars().all())


# --- provider_availability ------------------------------------------------


async def test_inserts_all_pa_posts_on_fresh_db(db_test_session_manager):
    await _insert_all_fixture_users()

    created, skipped = await seed.seed_provider_availability()

    assert (created, skipped) == (_PA_COUNT, 0)
    posts = await _all_pa_posts()
    assert len(posts) == _PA_COUNT


async def test_each_pa_post_has_populated_detail_relationship(db_test_session_manager):
    await _insert_all_fixture_users()

    await seed.seed_provider_availability()

    async with async_test_sessionmaker() as session:
        result = await session.execute(
            select(ProviderAvailabilityDetail).join(
                Post, Post.id == ProviderAvailabilityDetail.post_id
            )
        )
        details = list(result.scalars().all())

    # Practice name lives on the linked Provider's Organization (#524).
    practice_names = {d.provider.org.name for d in details}
    expected = {
        f["provider"]["practice_name"] for f in seed.FIXTURE_PROVIDER_AVAILABILITY
    }
    assert practice_names == expected


async def test_pa_rerun_is_idempotent(db_test_session_manager):
    await _insert_all_fixture_users()

    first = await seed.seed_provider_availability()
    second = await seed.seed_provider_availability()

    assert first == (_PA_COUNT, 0)
    assert second == (0, _PA_COUNT)
    assert len(await _all_pa_posts()) == _PA_COUNT


async def test_pa_skips_when_owner_missing(db_test_session_manager, capsys):
    # No fixture users seeded — every fixture row should be skipped.
    created, skipped = await seed.seed_provider_availability()

    assert created == 0
    assert skipped == _PA_COUNT
    assert await _all_pa_posts() == []


# --- client_referral ------------------------------------------------------


async def test_inserts_all_cr_posts_on_fresh_db(db_test_session_manager):
    await _insert_all_fixture_users()

    created, skipped = await seed.seed_client_referral()

    assert (created, skipped) == (_CR_COUNT, 0)
    posts = await _all_cr_posts()
    assert len(posts) == _CR_COUNT


async def test_each_cr_post_has_populated_detail_relationship(db_test_session_manager):
    await _insert_all_fixture_users()

    await seed.seed_client_referral()

    async with async_test_sessionmaker() as session:
        result = await session.execute(
            select(ClientReferralDetail).join(
                Post, Post.id == ClientReferralDetail.post_id
            )
        )
        details = list(result.scalars().all())

    descriptions = {d.description for d in details}
    expected = {f["detail"]["description"] for f in seed.FIXTURE_CLIENT_REFERRAL}
    assert descriptions == expected


async def test_cr_rerun_is_idempotent(db_test_session_manager):
    await _insert_all_fixture_users()

    first = await seed.seed_client_referral()
    second = await seed.seed_client_referral()

    assert first == (_CR_COUNT, 0)
    assert second == (0, _CR_COUNT)
    assert len(await _all_cr_posts()) == _CR_COUNT


async def test_cr_skips_when_owner_missing(db_test_session_manager):
    created, skipped = await seed.seed_client_referral()

    assert created == 0
    assert skipped == _CR_COUNT
    assert await _all_cr_posts() == []


# --- created_at variance --------------------------------------------------


async def test_seed_spreads_created_at_across_days(db_test_session_manager):
    """`days_ago` overrides the server-defaulted `created_at` so the
    listings feed shows a date range. Pins that the override actually
    takes effect — a regression collapsing all posts to `now()` would
    fail here."""
    await _insert_all_fixture_users()
    await seed.seed_provider_availability()
    await seed.seed_client_referral()

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
