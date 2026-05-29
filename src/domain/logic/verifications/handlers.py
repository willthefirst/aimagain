"""Verification orchestrator + bespoke trigger endpoint handler.

`run_clinician_verification` is the single callable both the nightly job
and the superuser retrigger endpoint here invoke.
"""

import logging
from uuid import UUID

import httpx

from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.verifications.nppes import NppesResult, nppes_lookup
from src.domain.logic.verifications.oig import oig_check
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.logic.verifications.schema import VerificationRead
from src.domain.logic.verifications.scoring import Score, score_verification
from src.domain.models import Clinician, User, Verification
from src.framework.audit.core import make_audited_resource, record_audit_for
from src.framework.audit.repository import AuditRepository
from src.framework.http.exceptions import ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)

VERIFICATION_RESOURCE = make_audited_resource("verification", VerificationRead)

HTTP_TIMEOUT_SECONDS = 10.0
_NPPES_SKIPPED_FLAG = "nppes_skipped"
_SKIPPED_NPPES = NppesResult(found=False, first_name=None, last_name=None, raw=None)


def _clinician_names(clinician: Clinician, owner: User | None) -> tuple[str, str]:
    """Best-available (first, last) name for a clinician.

    When BOTH are set, those become the names compared against NPPES + OIG.
    Falls back to (user.username, "") for legacy rows — routes to human
    review rather than silently "verifying" against a name we never had.
    """
    first = (clinician.first_name or "").strip()
    last = (clinician.last_name or "").strip()
    if first and last:
        return (first, last)
    if owner is None:
        return ("", "")
    return (owner.username or "", "")


async def run_clinician_verification(
    *,
    clinician_id: UUID,
    verification_repo: VerificationRepository,
    clinician_repo: ClinicianRepository,
    audit_repo: AuditRepository,
    http: httpx.AsyncClient,
    actor_id: UUID | None,
) -> Verification:
    """Run the full verification pipeline for one clinician and persist
    one `Verification` row plus one matching audit row in a single transaction.
    """
    clinician = await clinician_repo.get_by_model_id(Clinician, clinician_id)
    if clinician is None:
        raise NotFoundError(detail="Clinician not found")

    owner = await verification_repo.session.get(User, clinician.owner_id)
    first_name, last_name = _clinician_names(clinician, owner)

    extra_flags: list[str] = []
    if clinician.npi:
        nppes_result = await nppes_lookup(clinician.npi, http=http)
    else:
        nppes_result = _SKIPPED_NPPES
        extra_flags.append(_NPPES_SKIPPED_FLAG)

    oig_result = oig_check(
        first_name=first_name, last_name=last_name, npi=clinician.npi
    )
    score: Score = score_verification(
        nppes=nppes_result,
        oig=oig_result,
        clinician_first_name=first_name,
        clinician_last_name=last_name,
    )

    verification = await verification_repo.record(
        clinician_id=clinician.id,
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
        "verification: clinician=%s status=%s flags=%s actor=%s",
        clinician.id,
        score.status,
        verification.flags,
        actor_id,
    )
    return verification


async def handle_create_clinician_verification(
    clinician_id: UUID,
    verification_repo: VerificationRepository,
    clinician_repo: ClinicianRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> Verification:
    """Superuser-only manual retrigger of the verification pipeline."""
    if not requesting_user.is_superuser:
        raise ForbiddenError(detail="Verification retrigger is admin-only")

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
        return await run_clinician_verification(
            clinician_id=clinician_id,
            verification_repo=verification_repo,
            clinician_repo=clinician_repo,
            audit_repo=audit_repo,
            http=http,
            actor_id=requesting_user.id,
        )
