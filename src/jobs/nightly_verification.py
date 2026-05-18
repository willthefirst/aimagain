"""Nightly provider-verification job.

Iterates every non-deleted `Provider` and calls
`run_provider_verification(...)` (the orchestrator from #528) with
`actor_id=None` — the audit framework treats `None` as the system actor
(`AuditLog.actor_id` is nullable with `ON DELETE SET NULL`; see
`src/framework/audit/log.py`).

Each per-provider call owns its own transaction (the orchestrator
commits before returning), so a mid-loop failure can only lose the
provider it raised on — earlier providers' verification rows are durable
and later providers still run. Failures are logged with the offending
provider id; the loop never re-raises.

Sequential is intentional. NPPES is a free public registry with no
documented rate limit; the LEIE check is local. The per-call timeout
(see `_HTTP_TIMEOUT_SECONDS` in `src/domain/logic/verifications/handlers.py`)
bounds total runtime. If the provider count grows past O(1000), revisit
concurrency in a follow-up — don't bolt it on here.
"""

import logging

import httpx

from src.db import async_session_maker
from src.domain.logic.providers.repository import ProviderRepository
from src.domain.logic.verifications.handlers import run_provider_verification
from src.domain.logic.verifications.repository import VerificationRepository
from src.framework.audit.repository import AuditRepository

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS = 10.0


async def run_nightly_verification() -> None:
    async with async_session_maker() as session:
        provider_repo = ProviderRepository(session)
        verification_repo = VerificationRepository(session)
        audit_repo = AuditRepository(session)
        providers = await provider_repo.list_for_verification()

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as http:
            for provider in providers:
                try:
                    await run_provider_verification(
                        provider_id=provider.id,
                        verification_repo=verification_repo,
                        provider_repo=provider_repo,
                        audit_repo=audit_repo,
                        http=http,
                        actor_id=None,
                    )
                except Exception:
                    logger.exception(
                        "nightly verification failed for provider=%s", provider.id
                    )

    logger.info("nightly verification completed: %d providers", len(providers))
