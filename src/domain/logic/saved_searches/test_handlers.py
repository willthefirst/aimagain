"""Coverage for the bespoke ``handle_list_saved_searches`` gate.

A saved search is private: the generic list mount doesn't gate by
parent, so this handler carries the self-or-admin check. These tests
pin that gate (and the owner-scoping) directly; the route-level
end-to-end is in ``src/domain/routes/test_saved_searches.py``.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.logic.saved_searches.handlers import handle_list_saved_searches
from src.domain.logic.saved_searches.repository import SavedSearchRepository
from src.domain.models import SavedSearch, User
from src.framework.http.exceptions import ForbiddenError, NotFoundError


@pytest_asyncio.fixture
async def session(db_test_session_manager: async_sessionmaker):
    async with db_test_session_manager() as s:
        yield s


async def _make_user(session, *, is_superuser: bool = False) -> User:
    user = User(
        id=uuid.uuid4(),
        username=f"ss-h-{uuid.uuid4()}",
        email=f"{uuid.uuid4()}@example.com",
        hashed_password="not-a-password",
        is_active=True,
        is_verified=True,
        is_superuser=is_superuser,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_forbidden_for_other_user(session):
    owner = await _make_user(session)
    intruder = await _make_user(session)
    repo = SavedSearchRepository(session)
    await repo.create(SavedSearch(user_id=owner.id, name="Openings", filters={}))

    with pytest.raises(ForbiddenError):
        await handle_list_saved_searches(
            request=None, user_id=owner.id, repo=repo, requesting_user=intruder
        )


@pytest.mark.asyncio
async def test_owner_sees_only_their_rows(session):
    owner = await _make_user(session)
    other = await _make_user(session)
    repo = SavedSearchRepository(session)
    await repo.create(SavedSearch(user_id=owner.id, name="Openings", filters={}))
    await repo.create(SavedSearch(user_id=other.id, name="Theirs", filters={}))

    ctx = await handle_list_saved_searches(
        request=None, user_id=owner.id, repo=repo, requesting_user=owner
    )
    assert ctx["is_self"] is True
    assert [r.name for r in ctx["rows"]] == ["Openings"]


@pytest.mark.asyncio
async def test_admin_may_view_another_users_searches(session):
    owner = await _make_user(session)
    admin = await _make_user(session, is_superuser=True)
    repo = SavedSearchRepository(session)
    await repo.create(SavedSearch(user_id=owner.id, name="Openings", filters={}))

    ctx = await handle_list_saved_searches(
        request=None, user_id=owner.id, repo=repo, requesting_user=admin
    )
    assert ctx["is_self"] is False
    assert [r.name for r in ctx["rows"]] == ["Openings"]


@pytest.mark.asyncio
async def test_unknown_user_404s_for_admin(session):
    admin = await _make_user(session, is_superuser=True)
    repo = SavedSearchRepository(session)
    with pytest.raises(NotFoundError):
        await handle_list_saved_searches(
            request=None, user_id=uuid.uuid4(), repo=repo, requesting_user=admin
        )
