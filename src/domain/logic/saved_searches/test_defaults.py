"""Coverage for the default saved searches + their seeding helper."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.logic.saved_searches.defaults import (
    DEFAULT_SAVED_SEARCHES,
    seed_default_saved_searches,
)
from src.domain.models import SavedSearch, User
from src.domain.models.posts.post_kinds import POST_KINDS


@pytest_asyncio.fixture
async def session(db_test_session_manager: async_sessionmaker):
    async with db_test_session_manager() as s:
        yield s


async def _make_user(session) -> User:
    user = User(
        id=uuid.uuid4(),
        username=f"ss-def-{uuid.uuid4()}",
        email=f"{uuid.uuid4()}@example.com",
        hashed_password="not-a-password",
        is_active=True,
        is_verified=True,
    )
    session.add(user)
    await session.flush()
    return user


def test_default_kinds_are_valid_post_kinds():
    """Each default filters on a real `POST_KINDS` discriminator value —
    pins the defaults against a kind rename."""
    for _name, filters in DEFAULT_SAVED_SEARCHES:
        assert filters["kind"] in POST_KINDS.names


def test_defaults_are_openings_and_referrals():
    names = [name for name, _ in DEFAULT_SAVED_SEARCHES]
    assert names == ["Openings", "Referrals"]


@pytest.mark.asyncio
async def test_seed_creates_both_defaults(session):
    user = await _make_user(session)
    await seed_default_saved_searches(session, user.id)
    rows = (
        (
            await session.execute(
                select(SavedSearch).where(SavedSearch.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    by_name = {r.name: r.filters for r in rows}
    assert by_name == {
        "Openings": {"kind": "clinician_opening"},
        "Referrals": {"kind": "referral"},
    }


@pytest.mark.asyncio
async def test_seed_is_idempotent(session):
    """Re-running doesn't duplicate or trip the (user_id, name) UNIQUE."""
    user = await _make_user(session)
    await seed_default_saved_searches(session, user.id)
    await seed_default_saved_searches(session, user.id)
    count = len(
        (
            await session.execute(
                select(SavedSearch).where(SavedSearch.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert count == len(DEFAULT_SAVED_SEARCHES)
