"""Claim-cache recompute helpers and append-only event writer.

These two concerns are separated from the NPPES pipeline
(`handlers.py`) because they are used by callers outside the pipeline:
`clinicians/handlers.py` and `org_representations/handlers.py` both
need `recompute_clinician_claim` / `record_verification_event` without
pulling in the NPPES / HTTP dependencies.

`recompute_clinician_claim` and `recompute_org_claim` are nearly pure
functions (no I/O; they mutate their argument in place and the caller
commits).  `record_verification_event` is async + DB but has no HTTP
dependency — it is the single append-only writer for the non-NPPES §9
transitions.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.logic.verifications.schema import VerificationRead
from src.domain.models import Clinician, Organization, Verification
from src.framework.audit.core import make_audited_resource, record_audit_for
from src.framework.audit.repository import AuditRepository

logger = logging.getLogger(__name__)

VERIFICATION_RESOURCE = make_audited_resource("verification", VerificationRead)


def _now() -> datetime:
    """Single source of "now" so tests can patch one place if they need
    deterministic timestamps later."""
    return datetime.now(timezone.utc)


# ---------- Claim-cache recompute helpers --------------------------------


def recompute_clinician_claim(clinician: Clinician) -> None:
    """Compute `Clinician.clinician_verified` + the timestamp triplet
    (`verified_at`, `ever_verified_at`, regression detection) from the
    current `npi_match_status`, then mutate the clinician in place. The
    caller is responsible for committing the enclosing transaction.

    Claim A requires only an NPPES Type-1 name match
    (`npi_match_status == 'matched'`). Licensures and affiliations are
    tracked for display and credentialing but do not gate the claim —
    a solo practitioner with a matched NPI is fully verified.

    `ever_verified_at` is set on the first transition to True and
    preserved on regression — that's what powers the once-verified feed
    retention rule (handoff §7.1).
    """
    is_verified_now = clinician.npi_match_status == "matched"

    if is_verified_now:
        if not clinician.clinician_verified:
            clinician.verified_at = _now()
        clinician.clinician_verified = True
        if clinician.ever_verified_at is None:
            clinician.ever_verified_at = clinician.verified_at or _now()
    else:
        clinician.clinician_verified = False
        # Leave `verified_at` and `ever_verified_at` alone — the
        # first-ever timestamp is preserved across regressions so the
        # `can_act_as_provider` retention rule keeps working.


def recompute_org_claim(org: Organization) -> None:
    """Compute `Organization.org_verified` + `verified_at` from the
    current `npi_match_status`. Symmetric with the Clinician side,
    minus the licensure consideration (orgs don't hold licenses)."""
    is_verified_now = org.npi_match_status == "matched"
    if is_verified_now:
        if not org.org_verified:
            org.verified_at = _now()
        org.org_verified = True
    else:
        org.org_verified = False


# ---------- Append-only event writer -------------------------------------


async def record_verification_event(
    *,
    verification_repo: VerificationRepository,
    audit_repo: AuditRepository,
    subject_type: str,
    clinician_id: UUID | None = None,
    org_id: UUID | None = None,
    event_type: str,
    status: str = "verified",
    evidence: dict[str, Any] | None = None,
    actor_id: UUID | None,
) -> Verification:
    """Single append-only writer for the non-NPPES §9 transitions
    (`license_attested`, `license_expired`, `authority_proven`,
    `authority_revoked`, `role_set`, `admin_verify`, `admin_suspend`,
    `email_confirmed`). Records both a `Verification` row and a matching
    audit entry in one transaction; the caller is responsible for the
    enclosing `session.commit()`.

    The NPPES-pipeline writes (`npi_submitted`, `npi_resolved`) go
    through the dedicated `record_for_*` repository methods invoked
    inside `run_clinician_verification` / `run_org_verification` instead
    — they carry NPPES-specific fields (`nppes_result`, `oig_match`,
    `name_match_score`) the non-NPPES events don't have.
    """
    if (clinician_id is None) == (org_id is None):
        # Mirror the DB-level CHECK in Python so misuses fail loudly
        # at the handler boundary rather than as a SQLite IntegrityError.
        raise ValueError(
            "record_verification_event requires exactly one of " "clinician_id / org_id"
        )

    if subject_type == "clinician":
        assert clinician_id is not None  # narrowed by the XOR above
        verification = await verification_repo.record_for_clinician(
            clinician_id=clinician_id,
            status=status,
            flags=[],
            nppes_result=None,
            oig_match=False,
            name_match_score=None,
            event_type=event_type,
            evidence=evidence,
        )
    else:
        assert org_id is not None
        verification = await verification_repo.record_for_org(
            org_id=org_id,
            status=status,
            flags=[],
            nppes_result=None,
            name_match_score=None,
            event_type=event_type,
            evidence=evidence,
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
    return verification
