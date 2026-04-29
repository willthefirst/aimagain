"""Tests for `record_audit` logic helper.

The helper is a thin wrapper around `AuditRepository.record(...)`. These
tests verify the calling convention used by mutation handlers in PRs B/C/D
(retrofit posts/users/auth) — the contract is the kwargs they pass, not the
internals of the repo.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.logic.audit import AuditAction, record_audit
from src.repositories.audit_repository import AuditRepository
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio


async def test_record_audit_round_trips_through_repo(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Helper persists a row that can be fetched back via the repo."""
    actor = create_test_user(username=f"actor-{uuid.uuid4()}")
    resource_id = uuid.uuid4()

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(actor)

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        row = await record_audit(
            repo,
            actor_id=actor.id,
            resource_type="post",
            resource_id=resource_id,
            action=AuditAction.CREATE_POST,
            before=None,
            after={"title": "x"},
        )
        await session.commit()

        fetched = await repo.get_by_id(row.id)
        assert fetched is not None
        assert fetched.action == AuditAction.CREATE_POST
        assert fetched.before is None
        assert fetched.after == {"title": "x"}


async def test_record_audit_does_not_commit(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The helper flushes; it must not commit. Handlers commit after their
    own mutation + the audit call so the two land atomically.
    """
    actor = create_test_user(username=f"actor-{uuid.uuid4()}")
    resource_id = uuid.uuid4()

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(actor)

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        await record_audit(
            repo,
            actor_id=actor.id,
            resource_type="post",
            resource_id=resource_id,
            action=AuditAction.CREATE_POST,
            after={"title": "x"},
        )
        await session.rollback()

    # Outside the rolled-back session, no row should be visible.
    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(
            resource_type="post", resource_id=resource_id
        )
        assert rows == []


async def test_record_audit_accepts_null_actor(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Self-signup has no authenticated actor when the audit row is written."""
    resource_id = uuid.uuid4()

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        row = await record_audit(
            repo,
            actor_id=None,
            resource_type="user",
            resource_id=resource_id,
            action=AuditAction.REGISTER,
            after={"email": "new@example.com"},
        )
        await session.commit()

        assert row.actor_id is None
