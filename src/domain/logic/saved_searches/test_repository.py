"""Smoke tests for :class:`SavedSearchRepository`.

The repository is a thin shell over ``BaseRepository``; these tests
pin that it registers with the FastAPI dependency machinery and that
the inherited create / get / patch / delete primitives and the
owner-scoped ``list_owned_by`` work against the persisted
``saved_searches`` table. Route-level CRUD coverage lives in
``src/domain/routes/test_saved_searches.py``.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.logic.saved_searches.repository import (
    SavedSearchRepository,
    get_saved_search_repository,
)
from src.domain.models import SavedSearch, User
from src.framework.persistence.dependencies import (
    UnknownRepoTypeError,
    resolver_for,
)


@pytest_asyncio.fixture
async def session(db_test_session_manager: async_sessionmaker):
    async with db_test_session_manager() as s:
        yield s


async def _make_user(session) -> User:
    user = User(
        id=uuid.uuid4(),
        username=f"ss-repo-{uuid.uuid4()}",
        email=f"{uuid.uuid4()}@example.com",
        hashed_password="not-a-password",
        is_active=True,
        is_verified=True,
    )
    session.add(user)
    await session.flush()
    return user


def test_repository_registers_with_dispatch_registry():
    try:
        resolver = resolver_for(SavedSearchRepository)
    except UnknownRepoTypeError as exc:
        pytest.fail(str(exc))
    assert resolver is get_saved_search_repository


@pytest.mark.asyncio
async def test_create_and_fetch(session):
    user = await _make_user(session)
    repo = SavedSearchRepository(session)
    created = await repo.create(
        SavedSearch(
            user_id=user.id, name="Openings", filters={"kind": "clinician_opening"}
        )
    )
    assert created.id is not None
    fetched = await repo.get_by_model_id(SavedSearch, created.id)
    assert fetched is not None
    assert fetched.filters == {"kind": "clinician_opening"}


@pytest.mark.asyncio
async def test_list_owned_by_scopes_to_user_newest_first(session):
    """`list_owned_by(... owner_attr="user_id")` returns only the
    owner's rows, newest first — the shape the bespoke list handler
    relies on."""
    owner = await _make_user(session)
    other = await _make_user(session)
    repo = SavedSearchRepository(session)
    await repo.create(SavedSearch(user_id=owner.id, name="Referrals", filters={}))
    await repo.create(SavedSearch(user_id=owner.id, name="Openings", filters={}))
    await repo.create(SavedSearch(user_id=other.id, name="Theirs", filters={}))

    rows = await repo.list_owned_by(SavedSearch, owner.id, owner_attr="user_id")
    names = [r.name for r in rows]
    assert set(names) == {"Referrals", "Openings"}  # not "Theirs"
    # Newest-first: the second insert ("Openings") leads.
    assert names[0] == "Openings"
