"""Tests for `record_audit`, `record_audit_for`, and `mutate` helpers.

These tests verify the calling convention used by mutation handlers — the
contract is the kwargs they pass, not the internals of the repo.
"""

import uuid
from datetime import datetime

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.framework.audit.core import (
    AuditAction,
    AuditedResource,
    make_audited_resource,
    make_snapshotter,
    mutate,
    record_audit,
)
from src.framework.audit.log import AuditLog
from src.framework.audit.repository import AuditRepository
from src.framework.persistence.base_repository import BaseRepository
from tests.helpers import create_test_user

# No module-level `pytestmark = pytest.mark.asyncio` — `asyncio_mode =
# "auto"` in pyproject.toml already auto-marks async test functions,
# and applying the mark to the module triggers a warning on every sync
# test in this file.


class _ExampleSnapshot(BaseModel):
    id: uuid.UUID
    name: str
    when: datetime

    model_config = {"from_attributes": True}


def test_make_snapshotter_returns_json_mode_dict():
    """The snapshotter validates an ORM-shaped object and returns a dict
    whose datetime/uuid values are serialized as strings (JSON mode)."""

    class _Row:
        def __init__(self):
            self.id = uuid.uuid4()
            self.name = "foo"
            self.when = datetime(2026, 1, 1, 12, 0, 0)

    row = _Row()
    snap = make_snapshotter(_ExampleSnapshot)(row)

    assert snap == {
        "id": str(row.id),
        "name": "foo",
        "when": "2026-01-01T12:00:00",
    }


# --- make_audited_resource() --------------------------------------------


def test_make_audited_resource_derives_actions_from_name():
    """Default path: stem = name.upper(), actions looked up by convention."""
    resource = make_audited_resource("user", _ExampleSnapshot)
    assert resource.type == "user"
    assert resource.create is AuditAction.CREATE_USER
    assert resource.update is AuditAction.UPDATE_USER
    assert resource.delete is AuditAction.DELETE_USER


def test_make_audited_resource_wraps_schema_class_via_snapshotter():
    """A Pydantic schema class is wrapped so the snapshot callable behaves
    identically to one built via `make_snapshotter` directly."""

    class _Row:
        def __init__(self):
            self.id = uuid.uuid4()
            self.name = "foo"
            self.when = datetime(2026, 1, 1, 12, 0, 0)

    resource = make_audited_resource("user", _ExampleSnapshot)
    row = _Row()
    assert resource.snapshot(row) == {
        "id": str(row.id),
        "name": "foo",
        "when": "2026-01-01T12:00:00",
    }


def test_make_audited_resource_accepts_prebuilt_callable():
    """Posts' audit-snapshot is a hand-rolled discriminated-union callable
    rather than a single Pydantic class; the factory accepts it as-is."""
    sentinel = {"shape": "custom"}

    def _snap(_obj):
        return sentinel

    resource = make_audited_resource("post", _snap)
    assert resource.snapshot(object()) is sentinel
    assert resource.create is AuditAction.CREATE_POST


def test_make_audited_resource_honors_action_stem_override():
    """`provider_licensure` -> `CREATE_LICENSURE` etc. — entity name and
    enum stem diverge, so the caller passes `action_stem` explicitly."""
    resource = make_audited_resource(
        "provider_licensure", _ExampleSnapshot, action_stem="licensure"
    )
    assert resource.type == "provider_licensure"
    assert resource.create is AuditAction.CREATE_LICENSURE
    assert resource.update is AuditAction.UPDATE_LICENSURE
    assert resource.delete is AuditAction.DELETE_LICENSURE


def test_make_audited_resource_raises_on_missing_action():
    """Surfacing the missing-member case at import time beats a runtime
    KeyError from inside a mutation."""
    with pytest.raises(ValueError, match="CREATE_NONEXISTENT"):
        make_audited_resource("nonexistent", _ExampleSnapshot)


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

        fetched = await repo.get_by_model_id(AuditLog, row.id)
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
        post_repo = BaseRepository(session)

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
