"""Pending-NPI verification worker.

Polls `Clinician.list_pending_npi()` + `Organization.list_pending_npi()`
on a short interval and runs the matching NPPES pipeline against each
queued row. End-user "submit NPI" actions (Profile Hub `_claim_a_card`
/ `_claim_b_card`) set `npi_match_status='pending'` and then return
immediately; this job drains the queue.

Sequential per pipeline (same justification as `nightly_verification`):
NPPES has no documented rate limit and the per-call timeout bounds
total runtime. Each per-row call owns its own transaction, so a single
failure can't poison the queue — the loop logs and moves on.

Cadence: configurable via `JOBS_VERIFY_PENDING_NPIS_INTERVAL_SEC`. In
dev a tight ~60s loop gives a near-instant "Verifying…" → matched
transition; production can dial back to ~300s once the queue depth is
known.
"""

import logging

import httpx

from src.db import async_session_maker
from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.verifications.handlers import (
    HTTP_TIMEOUT_SECONDS,
    run_clinician_verification,
    run_org_verification,
)
from src.domain.logic.verifications.repository import VerificationRepository
from src.framework.audit.repository import AuditRepository

logger = logging.getLogger(__name__)


async def run_verify_pending_npis() -> None:
    """Drain the pending-NPI queues for both Clinician (Claim A,
    Type-1) and Organization (Claim B, Type-2)."""
    async with async_session_maker() as session:
        clinician_repo = ClinicianRepository(session)
        org_repo = OrganizationRepository(session)
        verification_repo = VerificationRepository(session)
        audit_repo = AuditRepository(session)
        pending_clinicians = await clinician_repo.list_pending_npi()
        pending_orgs = await org_repo.list_pending_npi()

        if not pending_clinicians and not pending_orgs:
            logger.debug("verify_pending_npis: queue empty")
            return

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
            for clinician in pending_clinicians:
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
                        "verify_pending_npis: clinician=%s failed", clinician.id
                    )
            for org in pending_orgs:
                try:
                    await run_org_verification(
                        org_id=org.id,
                        verification_repo=verification_repo,
                        org_repo=org_repo,
                        audit_repo=audit_repo,
                        http=http,
                        actor_id=None,
                    )
                except Exception:
                    logger.exception("verify_pending_npis: org=%s failed", org.id)

    logger.info(
        "verify_pending_npis: drained %d clinicians + %d orgs",
        len(pending_clinicians),
        len(pending_orgs),
    )
