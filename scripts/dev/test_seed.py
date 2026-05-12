"""Tests for `scripts/dev/seed.py`.

Two invariants matter beyond "the script ran":
  - On a fresh DB, `seed_provider_availability` inserts the full fixture
    set and populates each parent `Post` with its detail row in the
    same flush. A regression where the parent is committed without the
    detail would 500 every read view that joins the detail in.
  - Re-running is a no-op. The idempotency key (kind, owner_id,
    practice_name) keeps `dev seed` safe to run repeatedly during
    development.
"""

import pytest
from sqlalchemy import select

from scripts.dev import seed
from src.domain.models import Post, ProviderAvailabilityDetail, User
from tests.fixtures import async_test_sessionmaker
from tests.helpers import create_test_user


@pytest.fixture(autouse=True)
def patch_session_maker(monkeypatch):
    """Point the seed script at the in-memory test database."""
    monkeypatch.setattr(seed, "async_session_maker", async_test_sessionmaker)


async def _insert_alice() -> User:
    user = create_test_user(email="alice@example.com", username="alice")
    async with async_test_sessionmaker() as session:
        async with session.begin():
            session.add(user)
    return user


async def _all_pa_posts() -> list[Post]:
    async with async_test_sessionmaker() as session:
        result = await session.execute(
            select(Post).where(Post.kind == "provider_availability")
        )
        return list(result.scalars().all())


async def test_inserts_three_pa_posts_on_fresh_db(db_test_session_manager):
    await _insert_alice()

    created, skipped = await seed.seed_provider_availability()

    assert (created, skipped) == (3, 0)
    posts = await _all_pa_posts()
    assert len(posts) == 3


async def test_each_post_has_populated_detail_relationship(db_test_session_manager):
    await _insert_alice()

    await seed.seed_provider_availability()

    async with async_test_sessionmaker() as session:
        result = await session.execute(
            select(ProviderAvailabilityDetail).join(
                Post, Post.id == ProviderAvailabilityDetail.post_id
            )
        )
        details = list(result.scalars().all())

    # Practice name lives on the linked Provider (#448); dereference via
    # the FK relationship on the detail row.
    practice_names = {d.provider.practice_name for d in details}
    assert practice_names == {"Katie Reeves, PhD", "Camp BooHoo", "RISE IOP at CHC"}


async def test_rerun_is_idempotent(db_test_session_manager):
    await _insert_alice()

    first = await seed.seed_provider_availability()
    second = await seed.seed_provider_availability()

    assert first == (3, 0)
    assert second == (0, 3)
    assert len(await _all_pa_posts()) == 3


async def test_skips_when_owner_missing(db_test_session_manager, capsys):
    # No alice in this test — every fixture row should be skipped, nothing inserted.
    created, skipped = await seed.seed_provider_availability()

    assert created == 0
    assert skipped == 3
    assert await _all_pa_posts() == []
