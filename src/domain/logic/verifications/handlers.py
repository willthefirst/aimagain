"""Verification orchestrator + bespoke trigger endpoint handler.

`run_provider_verification` is the single callable both the nightly job
and the superuser retrigger endpoint here invoke. It composes the
NPPES + OIG + scoring primitives with the persistence rails and a
caller-owned `httpx.AsyncClient`, writes one `Verification` row plus
one matching audit row in a single transaction, and commits.

Why `record_audit_for(...)` and an explicit commit, not `mutate(...)`:
`mutate` is a snapshot-before / mutate / record_audit / commit ritual
built around a pre-existing target. Verification rows are *created*
each run — there is no pre-existing target to snapshot, so `mutate`'s
shape doesn't apply. The favorites cluster
(`src/domain/logic/favorites/handlers.py`) uses the same pattern for
the same reason; the next reader inclined to "refactor to mutate"
should leave this alone.
"""

import logging
from uuid import UUID

import httpx

from src.domain.logic.providers.repository import ProviderRepository
from src.domain.logic.verifications.nppes import NppesResult, nppes_lookup
from src.domain.logic.verifications.oig import oig_check
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.logic.verifications.schema import VerificationRead
from src.domain.logic.verifications.scoring import Score, score_verification
from src.domain.models import Provider, User, Verification
from src.framework.audit.core import make_audited_resource, record_audit_for
from src.framework.audit.repository import AuditRepository
from src.framework.http.exceptions import ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)


# Single `AuditedResource` for the whole cluster — declared at module
# top so the `AuditAction[CREATE_VERIFICATION/UPDATE_VERIFICATION/
# DELETE_VERIFICATION]` lookup fails fast at import time if the enum
# triple ever drifts. See `_BESPOKE` in
# `src/framework/audit/test_audit_action_drift.py` for why these
# AuditAction members exist without an `EntitySpec`.
VERIFICATION_RESOURCE = make_audited_resource("verification", VerificationRead)

_HTTP_TIMEOUT_SECONDS = 10.0

# NPPES is skipped when the provider has no NPI on file. The flag is
# surfaced so a reviewer can tell "we didn't try" from "we tried and
# missed." Closed vocabulary; do not invent flag tokens at call sites.
_NPPES_SKIPPED_FLAG = "nppes_skipped"

# Empty NPPES result used when the provider has no NPI to look up.
_SKIPPED_NPPES = NppesResult(found=False, first_name=None, last_name=None, raw=None)


def _clinician_names(provider: Provider, owner: User | None) -> tuple[str, str]:
    """Best-available (first, last) name for a provider's clinician.

    Reads `provider.first_name` / `last_name` (proxies to the linked
    `Clinician` row — the actual column owner). When BOTH are set,
    those become the names the NPPES + OIG scorers compare against;
    that's the path that lets a verification actually pass.

    When either is missing — legacy rows that predate the columns, or a
    half-filled edit form — falls back to `(user.username, "")`. The
    username fallback scores far below threshold (`needs_review`), so
    the verification routes to a human reviewer rather than silently
    "verifying" against a name we never actually had. Same posture as
    the original `_user_names`; this just reads from the right place
    once the columns are available.
    """
    first = (provider.first_name or "").strip()
    last = (provider.last_name or "").strip()
    if first and last:
        return (first, last)
    if owner is None:
        return ("", "")
    return (owner.username or "", "")


async def run_provider_verification(
    *,
    provider_id: UUID,
    verification_repo: VerificationRepository,
    provider_repo: ProviderRepository,
    audit_repo: AuditRepository,
    http: httpx.AsyncClient,
    actor_id: UUID | None,
) -> Verification:
    """Run the full verification pipeline for one provider and persist
    one `Verification` row plus one matching audit row in a single
    transaction.

    `actor_id=None` is legal — `AuditLog.actor_id` is nullable with
    `ON DELETE SET NULL` (`src/framework/audit/log.py`), and the
    nightly job runs with no requesting user.

    Raises `NotFoundError` if `provider_id` does not exist. Network /
    file failures inside NPPES / OIG degrade to "not found" / "no
    match" silently — those layers never raise.
    """
    provider = await provider_repo.get_by_model_id(Provider, provider_id)
    if provider is None:
        raise NotFoundError(detail="Provider not found")

    # Explicit fetch of the owning User so we don't trip
    # `Provider.user`'s default-lazy relationship in an async context
    # (the relationship isn't `selectin`-loaded). Sharing the session
    # with the repos keeps everything inside the orchestrator's
    # transaction.
    owner = await verification_repo.session.get(User, provider.owner_id)
    first_name, last_name = _clinician_names(provider, owner)

    extra_flags: list[str] = []
    if provider.npi:
        nppes_result = await nppes_lookup(provider.npi, http=http)
    else:
        nppes_result = _SKIPPED_NPPES
        extra_flags.append(_NPPES_SKIPPED_FLAG)

    oig_result = oig_check(first_name=first_name, last_name=last_name, npi=provider.npi)
    score: Score = score_verification(
        nppes=nppes_result,
        oig=oig_result,
        provider_first_name=first_name,
        provider_last_name=last_name,
    )

    verification = await verification_repo.record(
        provider_id=provider.id,
        status=score.status,
        flags=extra_flags + score.flags,
        nppes_result=nppes_result.raw,
        oig_match=oig_result.match,
        name_match_score=score.name_match_score,
    )
    await record_audit_for(
        audit_repo,
        resource=VERIFICATION_RESOURCE,
        verb="create",
        actor_id=actor_id,
        target_id=verification.id,
        before=None,
        after=VERIFICATION_RESOURCE.snapshot(verification),
    )
    await verification_repo.session.commit()
    logger.info(
        "verification: provider=%s status=%s flags=%s actor=%s",
        provider.id,
        score.status,
        verification.flags,
        actor_id,
    )
    return verification


async def handle_create_provider_verification(
    provider_id: UUID,
    verification_repo: VerificationRepository,
    provider_repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> Verification:
    """Superuser-only manual retrigger of the verification pipeline.

    Provider owners get verification automatically from the nightly job;
    this endpoint exists for admins to force a re-check on demand.
    Constructs a single-use `httpx.AsyncClient` for the call duration —
    the orchestrator owns the client's lifecycle.
    """
    if not requesting_user.is_superuser:
        raise ForbiddenError(detail="Verification retrigger is admin-only")

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as http:
        return await run_provider_verification(
            provider_id=provider_id,
            verification_repo=verification_repo,
            provider_repo=provider_repo,
            audit_repo=audit_repo,
            http=http,
            actor_id=requesting_user.id,
        )
