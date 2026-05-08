"""Tests for `record_audit`, `record_audit_for`, and `mutate` helpers.

These tests verify the calling convention used by mutation handlers — the
contract is the kwargs they pass, not the internals of the repo.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.logic.audit import (
    AuditAction,
    AuditedResource,
    mutate,
    record_audit,
)
from src.repositories.audit_repository import AuditRepository
from src.repositories.post_repository import PostRepository
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


# --- mutate() context manager --------------------------------------------


_TEST_RESOURCE = AuditedResource(
    type="post",
    snapshot=lambda obj: {"id": str(obj.id)},
    create=AuditAction.CREATE_POST,
    update=AuditAction.UPDATE_POST,
    delete=AuditAction.DELETE_POST,
)


async def test_mutate_does_not_commit_or_audit_when_body_raises(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Load-bearing contract: an exception inside `async with mutate(...)`
    must skip both the audit row and the commit so the transaction can
    roll back atomically. Without this, a handler that raises mid-flow
    would leave a dangling audit row pointing at a non-existent mutation.
    """
    actor = create_test_user(username=f"actor-{uuid.uuid4()}")
    resource_id = uuid.uuid4()

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(actor)

    class _FakeTarget:
        def __init__(self, target_id):
            self.id = target_id

    target = _FakeTarget(resource_id)

    async with db_test_session_manager() as session:
        audit_repo = AuditRepository(session)
        post_repo = PostRepository(session)

        with pytest.raises(RuntimeError, match="boom"):
            async with mutate(
                post_repo,
                audit_repo,
                actor=actor,
                target=target,
                resource=_TEST_RESOURCE,
                verb="update",
            ):
                raise RuntimeError("boom")

        # Roll back to mirror what a route handler would do on an
        # uncaught exception.
        await session.rollback()

    # In a fresh session, no audit row exists for this resource_id.
    async with db_test_session_manager() as session:
        audit_repo = AuditRepository(session)
        rows = await audit_repo.list_for_resource(
            resource_type=_TEST_RESOURCE.type, resource_id=resource_id
        )
        assert rows == [], "mutate() must not emit an audit row when its body raises"
