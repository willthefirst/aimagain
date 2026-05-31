"""Verification orchestrator + bespoke trigger endpoint handlers.

Two pipelines + a per-claim cache recompute + an append-only event
writer. The pipelines (`run_clinician_verification`,
`run_org_verification`) own NPPES + scoring + persistence; the recompute
helpers translate the latest event log + denormalized columns into the
boolean cache the capability predicates read; `record_verification_event`
appends the non-NPPES transitions from §9 (licensure attestation,
authority grant/revoke, admin override) so the event history stays a
single source of truth.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx

from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.verifications.nppes import (
    NppesOrgResult,
    NppesResult,
    nppes_lookup,
    nppes_lookup_type2,
)
from src.domain.logic.verifications.oig import oig_check
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.logic.verifications.schema import VerificationRead
from src.domain.logic.verifications.scoring import (
    Score,
    _name_similarity,
    score_verification,
)
from src.domain.models import Clinician, Organization, User, Verification
from src.framework.audit.core import make_audited_resource, record_audit_for
from src.framework.audit.repository import AuditRepository
from src.framework.http.exceptions import ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)

VERIFICATION_RESOURCE = make_audited_resource("verification", VerificationRead)

HTTP_TIMEOUT_SECONDS = 10.0
_NPPES_SKIPPED_FLAG = "nppes_skipped"
_NPPES_ORG_NAME_THRESHOLD = 0.80
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


def _now() -> datetime:
    """Single source of "now" for the orchestrator so tests can patch
    one place if they need deterministic timestamps later."""
    return datetime.now(timezone.utc)


# ---------- Clinician (Claim A) pipeline ---------------------------------


async def run_clinician_verification(
    *,
    clinician_id: UUID,
    verification_repo: VerificationRepository,
    clinician_repo: ClinicianRepository,
    audit_repo: AuditRepository,
    http: httpx.AsyncClient,
    actor_id: UUID | None,
) -> Verification:
    """Run the full Claim-A verification pipeline for one clinician and
    persist one `Verification` row plus one matching audit row in a
    single transaction. Also writes through the Claim-A denorm cache
    (`Clinician.npi_match_status`, `clinician_verified`, `verified_at`,
    `ever_verified_at`) per handoff §9.
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

    verification = await verification_repo.record_for_clinician(
        clinician_id=clinician.id,
        status=score.status,
        flags=extra_flags + score.flags,
        nppes_result=nppes_result.raw,
        oig_match=oig_result.match,
        name_match_score=score.name_match_score,
        event_type="npi_resolved",
        evidence=None,
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

    # Update the Claim-A denorm cache. Per handoff §10.1 the worker
    # never auto-transitions to `mismatch` — a soft mismatch stays
    # `pending` until an admin closes it via the `verification` state
    # axis on Clinician (Phase 1 ships the column but not the axis
    # handler yet; Phase 8's worker calls into this same code).
    if score.status == "verified":
        clinician.npi_match_status = "matched"
        clinician.npi_verified_at = _now()
    elif score.status == "failed" and not clinician.npi:
        # No NPI submitted yet — stay at 'none' rather than burning the
        # column to a final-fail state the user can't recover from
        # without admin intervention.
        clinician.npi_match_status = "none"
    # `needs_review` and "found but mismatch" stay `pending` until an
    # admin closes the loop.
    recompute_clinician_claim(clinician)

    await verification_repo.session.commit()
    logger.info(
        "verification.clinician: id=%s status=%s flags=%s actor=%s",
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
    """Superuser-only manual retrigger of the Claim-A verification pipeline."""
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


# ---------- Organization (Claim B prereq) pipeline -----------------------


def _score_org_name_match(
    nppes: NppesOrgResult, org_name: str
) -> tuple[str, list[str], float | None]:
    """Status + flags + similarity for a Type-2 NPPES result.

    Mirrors `score_verification`'s contract but specialized for org-name
    matching. The AO name match (the per-user authority path) is NOT
    scored here — it's owned by the `authorized_official` authority-
    method handler, which compares the AO name to the requesting user's
    verified `Clinician` name.
    """
    if not nppes.found:
        return ("failed", ["nppes_npi_not_found"], None)
    nppes_name = (nppes.org_name or "").strip()
    declared_name = (org_name or "").strip()
    if not nppes_name or not declared_name:
        return ("needs_review", ["nppes_org_name_missing"], None)
    similarity = _name_similarity(nppes_name, declared_name)
    if similarity < _NPPES_ORG_NAME_THRESHOLD:
        return ("needs_review", ["nppes_org_name_mismatch"], similarity)
    return ("verified", [], similarity)


async def run_org_verification(
    *,
    org_id: UUID,
    verification_repo: VerificationRepository,
    org_repo: OrganizationRepository,
    audit_repo: AuditRepository,
    http: httpx.AsyncClient,
    actor_id: UUID | None,
) -> Verification:
    """Run the Claim-B Type-2 NPPES verification pipeline for one org.

    Symmetric with `run_clinician_verification`: looks up the Type-2
    NPI, compares NPPES `organization_name` to `Organization.name`,
    persists a `Verification` row + audit row, and writes through the
    Claim-B denorm cache (`Organization.npi_match_status`,
    `org_verified`, `verified_at`, `authorized_official_name`).
    """
    org = await org_repo.get_by_model_id(Organization, org_id)
    if org is None:
        raise NotFoundError(detail="Organization not found")

    if org.npi:
        nppes_result = await nppes_lookup_type2(org.npi, http=http)
        flags: list[str] = []
    else:
        nppes_result = NppesOrgResult(
            found=False,
            org_name=None,
            authorized_official_name=None,
            raw=None,
        )
        flags = [_NPPES_SKIPPED_FLAG]

    status, score_flags, similarity = _score_org_name_match(nppes_result, org.name)

    verification = await verification_repo.record_for_org(
        org_id=org.id,
        status=status,
        flags=flags + score_flags,
        nppes_result=nppes_result.raw,
        name_match_score=similarity,
        event_type="npi_resolved",
        evidence=(
            {"authorized_official_name": nppes_result.authorized_official_name}
            if nppes_result.authorized_official_name
            else None
        ),
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

    # Update the org-side denorm cache. Same §10.1 rule as the Clinician
    # side: `needs_review` stays `pending` rather than auto-flipping to
    # `mismatch`.
    if status == "verified":
        org.npi_match_status = "matched"
        if nppes_result.authorized_official_name:
            org.authorized_official_name = nppes_result.authorized_official_name
    elif status == "failed" and not org.npi:
        org.npi_match_status = "none"
    recompute_org_claim(org)

    await verification_repo.session.commit()
    logger.info(
        "verification.org: id=%s status=%s flags=%s actor=%s",
        org.id,
        status,
        verification.flags,
        actor_id,
    )
    return verification


async def handle_create_org_verification(
    org_id: UUID,
    verification_repo: VerificationRepository,
    org_repo: OrganizationRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> Verification:
    """Superuser-only manual retrigger of the Claim-B verification pipeline."""
    if not requesting_user.is_superuser:
        raise ForbiddenError(detail="Verification retrigger is admin-only")

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
        return await run_org_verification(
            org_id=org_id,
            verification_repo=verification_repo,
            org_repo=org_repo,
            audit_repo=audit_repo,
            http=http,
            actor_id=requesting_user.id,
        )


# ---------- Claim-cache recompute helpers --------------------------------


def recompute_clinician_claim(clinician: Clinician) -> None:
    """Compute `Clinician.clinician_verified` + the timestamp triplet
    (`verified_at`, `ever_verified_at`, regression detection) from the
    current `npi_match_status` + the licensure set, then mutate the
    clinician in place. The caller is responsible for committing the
    enclosing transaction.

    Claim A requires:
      1. `npi_match_status == 'matched'`
      2. at least one `ClinicianLicensure` with `status == 'active'`

    `ever_verified_at` is set on the first transition to True and
    preserved on regression — that's what powers the once-verified feed
    retention rule (handoff §7.1).
    """
    matched = clinician.npi_match_status == "matched"
    licensures = getattr(clinician, "licensures", None) or ()
    has_active_license = any(
        getattr(lic, "status", None) == "active" for lic in licensures
    )
    is_verified_now = matched and has_active_license

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
        # `can_read_full_feed` retention rule keeps working.


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
