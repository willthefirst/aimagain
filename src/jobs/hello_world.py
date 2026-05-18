"""Hello-world job: the smallest possible proof that the APScheduler rails
work end-to-end.

Reads a session from `async_session_maker` (the same session factory the
HTTP layer uses) and writes a single `JOB_RUN_STARTED` audit row with the
system-actor convention (`actor_id=None`). The presence of this row in
`audit_log` after one interval is the canary that the scheduler is
running inside the app process and that jobs see the same DB the app
sees.
"""

import logging
from uuid import uuid4

from src.db import async_session_maker
from src.framework.audit.core import AuditAction, record_audit
from src.framework.audit.repository import AuditRepository

logger = logging.getLogger(__name__)


async def run_hello_world() -> None:
    async with async_session_maker() as session:
        audit_repo = AuditRepository(session)
        await record_audit(
            audit_repo,
            actor_id=None,
            resource_type="job",
            resource_id=uuid4(),
            action=AuditAction.JOB_RUN_STARTED,
            before=None,
            after={"job": "hello_world"},
        )
        await session.commit()
    logger.info("hello_world job completed")
