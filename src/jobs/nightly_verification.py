"""Nightly clinician-verification job.

Iterates every non-deleted `Clinician` and calls
`run_clinician_verification(...)` with `actor_id=None` — the audit
framework treats `None` as the system actor.

Each per-clinician call owns its own transaction (the orchestrator
commits before returning), so a mid-loop failure can only lose the
clinician it raised on — earlier verification rows are durable and
later clinicians still run. Failures are logged with the offending
clinician id; the loop never re-raises.

Sequential is intentional — NPPES is a free public registry with no
documented rate limit and the per-call timeout bounds total runtime.
"""

import logging

import httpx

from src.db import async_session_maker
from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.verifications.handlers import run_clinician_verification
from src.domain.logic.verifications.repository import VerificationRepository
from src.framework.audit.repository import AuditRepository

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS = 10.0


async def run_nightly_verification() -> None:
    async with async_session_maker() as session:
        clinician_repo = ClinicianRepository(session)
        verification_repo = VerificationRepository(session)
        audit_repo = AuditRepository(session)
        clinicians = await clinician_repo.list_for_verification()

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as http:
            for clinician in clinicians:
                try:
                    await run_clinician_verification(
                        clinician_id=clinician.id,
                        verification_repo=verification_repo,
                        clinician_repo=clinician_repo,
                        audit_repo=audit_repo,
                        http=http,
                        actor_id=None,
                    )
                except Exception:
                    logger.exception(
                        "nightly verification failed for clinician=%s", clinician.id
                    )

    logger.info("nightly verification completed: %d clinicians", len(clinicians))
