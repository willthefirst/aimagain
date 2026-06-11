"""NPPES verification pipeline handlers.

Two pipelines that own NPPES lookup + scoring + persistence + denorm
cache write-through.  The per-claim cache recompute helpers
(`recompute_clinician_claim`, `recompute_org_claim`) and the append-only
event writer (`record_verification_event`) live in `events.py` — they
are imported from there by callers outside this pipeline.
"""

import logging
from uuid import UUID

import httpx

from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.verifications.events import (
    VERIFICATION_RESOURCE,
    _now,
    recompute_clinician_claim,
    recompute_org_claim,
)
from src.domain.logic.verifications.nppes import (
    NppesOrgResult,
    NppesResult,
    nppes_lookup,
    nppes_lookup_type2,
)
from src.domain.logic.verifications.oig import oig_check
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.logic.verifications.scoring import (
    Score,
    _name_similarity,
    score_verification,
)
from src.domain.models import Clinician, Organization, User, Verification
from src.framework.audit.core import record_audit_for
from src.framework.audit.repository import AuditRepository
from src.framework.http.exceptions import ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 10.0
_NPPES_SKIPPED_FLAG = "nppes_skipped"
_NPPES_ORG_NAME_THRESHOLD = 0.80
_SKIPPED_NPPES = NppesResult(found=False, first_name=None, last_name=None, raw=None)


def npi_failure_message(verification: Verification) -> str:
    """Human-readable explanation of why a Verification didn't reach
    `status='verified'`. Used by the inline-create hooks to populate the
    400 banner so the form re-renders with a concrete next step.

    Reads `verification.flags` first (the closed-vocabulary tokens the
    scorer emits) and falls back to a generic message keyed off
    `verification.status` when no known flag matches.
    """
    flags = list(verification.flags or ())
    for flag in flags:
        if flag.startswith("oig_excluded"):
            return (
                "This NPI is on the OIG exclusion list and cannot be used "
                "to register a clinician or organization."
            )
        if flag == "nppes_npi_not_found":
            return (
                "We couldn't find that NPI in the federal NPPES registry. "
                "Double-check the 10-digit number and try again."
            )
        if flag == "nppes_name_mismatch":
            return (
                "The name on that NPI in NPPES doesn't match the first / "
                "last name you entered. Correct either field and resubmit."
            )
        if flag == "nppes_org_name_mismatch":
            return (
                "The organization name on that NPI in NPPES doesn't match "
                "what you entered. Correct either field and resubmit."
            )
        if flag == "nppes_org_name_missing":
            return (
                "NPPES returned this NPI without an organization name we "
                "could compare against. Double-check the NPI."
            )
        if flag == _NPPES_SKIPPED_FLAG:
            return "An NPI is required to register a clinician or organization."
    return (
        "We couldn't verify that NPI against the NPPES registry. "
        "Double-check the number and try again."
    )


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


# ---------- Clinician (Claim A) pipeline ---------------------------------


async def run_clinician_verification(
    *,
    clinician_id: UUID,
    verification_repo: VerificationRepository,
    clinician_repo: ClinicianRepository,
    audit_repo: AuditRepository,
    http: httpx.AsyncClient,
    actor_id: UUID | None,
    commit: bool = True,
) -> Verification:
    """Run the full Claim-A verification pipeline for one clinician and
    persist one `Verification` row plus one matching audit row in a
    single transaction. Also writes through the Claim-A denorm cache
    (`Clinician.npi_match_status`, `clinician_verified`, `verified_at`,
    `ever_verified_at`) per handoff §9.

    When `commit=False` the in-flight Verification row + audit row are
    queued on the session but not committed — the caller owns the
    transaction. Used by the inline-create hook so a verification
    failure can raise and roll back the still-uncommitted clinician
    row in one atomic unit.
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

    # Update the Claim-A denorm cache. Three outcomes map to two states
    # the worker doesn't re-poll:
    #
    # - `verified`: NPPES name match cleared the threshold → `matched`.
    # - `failed` / `needs_review` with NPI on file: NPPES gave a
    #   definitive non-match (NPI not found, OIG hit, name mismatch).
    #   Re-running NPPES against the same row won't change the answer,
    #   so flip to `mismatch` and stop polling. The original §10.1
    #   "never hard-fail without admin review" rule is preserved by the
    #   `verification` state axis on Clinician — admin can flip back
    #   to `pending` (to re-queue) or `matched` (to override) via
    #   `PUT /clinicians/{id}/verification`.
    # - `failed` with no NPI on file: nothing to lock in; stay at
    #   `none` so the next submission re-enters the pipeline cleanly.
    #
    # The `npi_resolved` Verification row above already captures the
    # NPPES result in the event log; a separate "cache transition"
    # event would just duplicate that.
    if score.status == "verified":
        clinician.npi_match_status = "matched"
        clinician.npi_verified_at = _now()
    elif score.status in ("failed", "needs_review"):
        if clinician.npi:
            clinician.npi_match_status = "mismatch"
        else:
            clinician.npi_match_status = "none"

    recompute_clinician_claim(clinician)

    if commit:
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
    commit: bool = True,
) -> Verification:
    """Run the Claim-B Type-2 NPPES verification pipeline for one org.

    Symmetric with `run_clinician_verification`: looks up the Type-2
    NPI, compares NPPES `organization_name` to `Organization.name`,
    persists a `Verification` row + audit row, and writes through the
    Claim-B denorm cache (`Organization.npi_match_status`,
    `org_verified`, `verified_at`, `authorized_official_name`).

    `commit=False` mirrors the clinician-side switch — the inline org
    create hook participates in the create transaction so a failed
    verification rolls back the row.
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

    # Update the org-side denorm cache. Mirror of the clinician-side
    # rule: `failed`/`needs_review` with an NPI on file → `mismatch`
    # (worker stops polling; admin flips via the `verification` state
    # axis on Organization if needed).
    if status == "verified":
        org.npi_match_status = "matched"
        if nppes_result.authorized_official_name:
            org.authorized_official_name = nppes_result.authorized_official_name
    elif status in ("failed", "needs_review"):
        if org.npi:
            org.npi_match_status = "mismatch"
        else:
            org.npi_match_status = "none"
    recompute_org_claim(org)

    if commit:
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
