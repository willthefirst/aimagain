"""Tests for `AuditRepository`.

Exercises the append-only contract: writes flush (not commit), reads return
oldest-first per resource, and the schema accepts a null `actor_id`
(unauthenticated mutations) plus null `before`/`after` (create has no
before, delete has no after).
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import User
from src.repositories.audit_repository import AuditRepository
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio


async def test_record_persists_row(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    actor = create_test_user(username=f"actor-{uuid.uuid4()}")
    resource_id = uuid.uuid4()

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(actor)

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        row = await repo.record(
            actor_id=actor.id,
            resource_type="post",
            resource_id=resource_id,
            action="create_post",
            before=None,
            after={"title": "x", "body": "y"},
        )
        await session.commit()

        assert row.id is not None
        assert row.actor_id == actor.id
        assert row.resource_type == "post"
        assert row.resource_id == resource_id
        assert row.action == "create_post"
        assert row.before is None
        assert row.after == {"title": "x", "body": "y"}
        assert row.created_at is not None  # doubles as `at`


async def test_record_accepts_null_actor(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Unauthenticated mutations (e.g. self-signup) have no actor."""
    resource_id = uuid.uuid4()

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        row = await repo.record(
            actor_id=None,
            resource_type="user",
            resource_id=resource_id,
            action="register",
            before=None,
            after={"email": "new@example.com"},
        )
        await session.commit()

        assert row.actor_id is None


async def test_record_accepts_null_after_for_delete(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    actor = create_test_user(username=f"actor-{uuid.uuid4()}")
    resource_id = uuid.uuid4()

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(actor)

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        row = await repo.record(
            actor_id=actor.id,
            resource_type="user",
            resource_id=resource_id,
            action="delete_user",
            before={"username": "old"},
            after=None,
        )
        await session.commit()

        assert row.before == {"username": "old"}
        assert row.after is None


async def test_get_by_id_returns_row(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    actor = create_test_user(username=f"actor-{uuid.uuid4()}")

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(actor)

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        written = await repo.record(
            actor_id=actor.id,
            resource_type="post",
            resource_id=uuid.uuid4(),
            action="create_post",
        )
        await session.commit()

        fetched = await repo.get_by_id(written.id)
        assert fetched is not None
        assert fetched.id == written.id


async def test_get_by_id_returns_none_for_unknown_id(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        assert await repo.get_by_id(uuid.uuid4()) is None


async def test_list_for_resource_returns_oldest_first(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Multiple audit rows for one resource come back in chronological order."""
    from datetime import datetime, timedelta, timezone

    actor = create_test_user(username=f"actor-{uuid.uuid4()}")
    resource_id = uuid.uuid4()

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(actor)

    now = datetime.now(timezone.utc)
    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        first = await repo.record(
            actor_id=actor.id,
            resource_type="post",
            resource_id=resource_id,
            action="create_post",
        )
        second = await repo.record(
            actor_id=actor.id,
            resource_type="post",
            resource_id=resource_id,
            action="update_post",
        )
        # Force determinism — two inserts can share `created_at` at SQLite
        # millisecond resolution.
        first.created_at = now - timedelta(seconds=1)
        second.created_at = now
        await session.commit()

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(
            resource_type="post", resource_id=resource_id
        )
        assert [r.action for r in rows] == ["create_post", "update_post"]


async def test_list_for_resource_filters_by_type_and_id(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    actor = create_test_user(username=f"actor-{uuid.uuid4()}")
    target = uuid.uuid4()
    other = uuid.uuid4()

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(actor)

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        await repo.record(
            actor_id=actor.id,
            resource_type="post",
            resource_id=target,
            action="create_post",
        )
        await repo.record(
            actor_id=actor.id,
            resource_type="post",
            resource_id=other,
            action="create_post",
        )
        await repo.record(
            actor_id=actor.id,
            resource_type="user",
            resource_id=target,  # same id, different type
            action="register",
        )
        await session.commit()

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=target)
        assert len(rows) == 1
        assert rows[0].resource_type == "post"
        assert rows[0].resource_id == target


async def test_actor_set_null_when_user_deleted(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Audit rows survive their actor — the FK cascades to NULL, not delete."""
    actor = create_test_user(username=f"actor-{uuid.uuid4()}")
    resource_id = uuid.uuid4()

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(actor)

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        written = await repo.record(
            actor_id=actor.id,
            resource_type="post",
            resource_id=resource_id,
            action="create_post",
        )
        await session.commit()

    # Delete the actor with FK enforcement enabled (SQLite needs the pragma).
    async with db_test_session_manager() as session:
        await session.execute(__import__("sqlalchemy").text("PRAGMA foreign_keys = ON"))
        target = await session.get(User, actor.id)
        await session.delete(target)
        await session.commit()

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        fetched = await repo.get_by_id(written.id)
        assert fetched is not None  # row not deleted
        assert fetched.actor_id is None  # actor reference nulled
