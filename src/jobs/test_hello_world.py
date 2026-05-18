"""Pins the hello-world rails: one audit row per invocation, system actor.

If this test fails after a change to `record_audit` or to the
`JOB_RUN_STARTED` action, you've either drifted the system-actor convention
or moved the audit call out of the job — see `src/jobs/README.md`.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.framework.audit.core import AuditAction
from src.framework.audit.log import AuditLog
from src.jobs import hello_world

pytestmark = pytest.mark.asyncio


async def test_run_hello_world_writes_one_system_actor_audit_row(
    monkeypatch: pytest.MonkeyPatch,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    monkeypatch.setattr(hello_world, "async_session_maker", db_test_session_manager)

    await hello_world.run_hello_world()

    async with db_test_session_manager() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.action == AuditAction.JOB_RUN_STARTED.value
    assert row.actor_id is None
    assert row.resource_type == "job"
    assert row.before is None
    assert row.after == {"job": "hello_world"}
