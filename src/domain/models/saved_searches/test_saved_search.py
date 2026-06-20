"""Model-layer coverage for :class:`SavedSearch`.

Pins the owner FK + CASCADE, the JSON `filters` round-trip (object,
not list), the empty-object default, and the `(user_id, name)` UNIQUE.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.models import SavedSearch, User


@pytest_asyncio.fixture
async def session(db_test_session_manager: async_sessionmaker):
    async with db_test_session_manager() as s:
        yield s


async def _make_user(session) -> User:
    user = User(
        id=uuid.uuid4(),
        username=f"ss-{uuid.uuid4()}",
        email=f"{uuid.uuid4()}@example.com",
        hashed_password="not-a-password",
        is_active=True,
        is_verified=True,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_filters_default_is_empty_object(session):
    """A row created without `filters` defaults to `{}` (the "no
    filters / whole directory" value), not None and not `[]`."""
    user = await _make_user(session)
    row = SavedSearch(user_id=user.id, name="All posts")
    session.add(row)
    await session.flush()
    await session.refresh(row)
    assert row.filters == {}


@pytest.mark.asyncio
async def test_filters_roundtrip_object(session):
    """The JSON column persists and returns a `filter_values`-shaped
    dict (scalars and repeated/multi values as lists)."""
    user = await _make_user(session)
    payload = {"kind": "clinician_opening", "state": ["CA", "NY"]}
    row = SavedSearch(user_id=user.id, name="CA/NY openings", filters=payload)
    session.add(row)
    await session.flush()
    fetched = await session.get(SavedSearch, row.id)
    assert fetched.filters == payload


@pytest.mark.asyncio
async def test_unique_name_per_user(session):
    """`(user_id, name)` is UNIQUE — a user can't hold two searches
    with the same name."""
    user = await _make_user(session)
    session.add(SavedSearch(user_id=user.id, name="Openings", filters={}))
    await session.flush()
    session.add(SavedSearch(user_id=user.id, name="Openings", filters={}))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_same_name_allowed_across_users(session):
    """The UNIQUE is scoped to the owner — two different users may each
    have an "Openings" search."""
    a = await _make_user(session)
    b = await _make_user(session)
    session.add(SavedSearch(user_id=a.id, name="Openings", filters={}))
    session.add(SavedSearch(user_id=b.id, name="Openings", filters={}))
    await session.flush()  # no IntegrityError


@pytest.mark.asyncio
async def test_cascade_delete_with_owner(session):
    """Deleting the owning user evicts their saved searches via the ORM
    `cascade="all, delete-orphan"` on `User.saved_searches`."""
    user = await _make_user(session)
    row = SavedSearch(user_id=user.id, name="Openings", filters={})
    session.add(row)
    await session.flush()
    row_id = row.id

    await session.delete(user)
    await session.flush()
    assert await session.get(SavedSearch, row_id) is None
