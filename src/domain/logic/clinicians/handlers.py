"""Clinician-directory orchestration handlers."""

import logging
from typing import Any
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel

from src.domain.logic.clinician_affiliations.repository import (
    ClinicianAffiliationRepository,
)
from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.favorites.repository import UserFavoriteRepository
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.users.repository import UserRepository
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import (
    Clinician,
    Organization,
    User,
)
from src.framework.access.authz.authz import assert_fk_ownership, list_visible_to
from src.framework.audit.repository import AuditRepository
from src.framework.dispatch.pagination import (
    DEFAULT_PAGE_SIZE,
    Pager,
    base_query,
    offset_for,
    paginate,
    parse_page,
)
from src.framework.http.exceptions import ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)


async def after_create_clinician_verification(
    *,
    row: Clinician,
    payload: BaseModel,
    requesting_user: User,
    verification_repo: VerificationRepository,
    clinician_repo: ClinicianRepository,
    verification_audit_repo: AuditRepository,
) -> None:
    """Run the NPI verification pipeline immediately after a clinician row
    is created, and **fail the create** if NPPES doesn't return a verified
    match. Produces one Verification row + audit row and writes through the
    Claim-A denorm cache.

    Runs inside the framework's `mutate(...)` block on
    `POST /clinicians` (see `CLINICIAN_ENTITY.after_create_path`). The
    pipeline runs with `commit=False` so its queued writes participate
    in the create transaction. On a non-verified outcome a
    `BadRequestError` is raised — `mutate`'s context manager skips the
    create-audit row and commit, SQLAlchemy rolls back the still-uncommitted
    session, and the user sees the form re-rendered with the per-flag
    explanation produced by `npi_failure_message`. The clinician row is
    never durable without a verified NPI.
    """
    import httpx

    from src.domain.logic.verifications.handlers import (
        HTTP_TIMEOUT_SECONDS,
        npi_failure_message,
        run_clinician_verification,
    )
    from src.framework.http.exceptions import BadRequestError

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
        verification = await run_clinician_verification(
            clinician_id=row.id,
            verification_repo=verification_repo,
            clinician_repo=clinician_repo,
            audit_repo=verification_audit_repo,
            http=http,
            actor_id=requesting_user.id,
            commit=False,
        )
    if verification.status != "verified":
        raise BadRequestError(detail=npi_failure_message(verification))
    # NB: no `session.refresh(row)` here. With `commit=False` the
    # `npi_match_status` / `npi_verified_at` / cache writes from the
    # pipeline are only in memory — they haven't reached the DB yet, so
    # `refresh` (which doesn't autoflush) would re-read the row and
    # silently revert the in-memory changes before the framework's
    # `mutate(...)` block reads them for the audit after-snapshot.

    # Restore the "every clinician has ≥1 ClinicianAffiliation"
    # invariant for solo clinicians who hit the create path without
    # supplying any per-affiliation field — practice posture lives on
    # the affiliation, and the proxy setters on `Clinician` raise when
    # none exists. The stub starts with `org_id` NULL and unset session
    # availability (NULL); the user fills those in from the edit form.
    if not row.clinician_affiliations:
        from src.domain.models import ClinicianAffiliation

        row.clinician_affiliations = [ClinicianAffiliation(clinician=row)]


async def after_update_clinician_verification(
    *,
    row: Clinician,
    payload: BaseModel,
    requesting_user: User,
    changed_fields: set[str],
    verification_repo: VerificationRepository,
    clinician_repo: ClinicianRepository,
    verification_audit_repo: AuditRepository,
) -> None:
    """Re-run NPI verification when a `PATCH /clinicians/{id}` changes the
    clinician's `npi`.

    Canonical replacement for the retired `POST /profile/clinician/{id}/identity`
    retry flow: editing the NPI on the clinician's own page re-checks NPPES
    instead of leaving the row stuck at its prior `npi_match_status`. Keyed
    on the *value* changing (not merely being present in the payload), so an
    edit that only touches location/availability doesn't fire a needless
    NPPES lookup. Other edits are a no-op.

    Unlike the create hook, this path does NOT raise on a non-verified
    outcome — an update to a bad NPI lands the row in
    `npi_match_status=mismatch`, the documented retry shape. The user
    can edit the NPI again from the edit page.
    """
    if "npi" not in changed_fields:
        return
    import httpx

    from src.domain.logic.verifications.handlers import (
        HTTP_TIMEOUT_SECONDS,
        run_clinician_verification,
    )

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
        await run_clinician_verification(
            clinician_id=row.id,
            verification_repo=verification_repo,
            clinician_repo=clinician_repo,
            audit_repo=verification_audit_repo,
            http=http,
            actor_id=requesting_user.id,
        )
    await clinician_repo.session.refresh(row)


async def _assert_clinician_payload_org_ownership(
    *,
    payload: BaseModel,
    requesting_user: User,
    organization_repo: OrganizationRepository,
) -> None:
    """Payload authz for clinician create/update.

    Delegates to the framework's FK-ownership guard. Create payloads
    never carry ``org_id`` (org assignment happens later via the
    affiliation sub-resource); update payloads may, and `assert_fk_ownership`
    treats a missing/None FK as a no-op.
    """
    await assert_fk_ownership(
        payload=payload,
        attr="org_id",
        requesting_user=requesting_user,
        parent_repo=organization_repo,
        parent_model=Organization,
        parent_noun="Organization",
        child_noun="Clinician",
    )


async def clinician_form_extras(
    *,
    target: Clinician | None,
    requesting_user: User,
    organization_repo: OrganizationRepository,
    **_: Any,
) -> dict[str, Any]:
    return {
        "orgs": await list_visible_to(organization_repo, requesting_user, Organization),
    }


async def clinician_detail_extras(
    *,
    target: Clinician,
    requesting_user: User | None,
    user_favorite_repo: UserFavoriteRepository,
    verification_repo: VerificationRepository,
    **_: Any,
) -> dict[str, Any]:
    latest = await verification_repo.latest_for_clinician(target.id)
    verification_status = latest.status if latest else None
    if requesting_user is None:
        return {"is_favorited": False, "verification_status": verification_status}
    return {
        "is_favorited": await user_favorite_repo.is_favorited(
            user_id=requesting_user.id, clinician_id=target.id
        ),
        "verification_status": verification_status,
    }


async def handle_list_user_clinicians(
    request: Request,
    user_id: UUID,
    repo: ClinicianRepository,
    user_repo: UserRepository,
    requesting_user: User,
) -> dict[str, Any]:
    if user_id != requesting_user.id and not requesting_user.is_superuser:
        raise ForbiddenError(
            detail="Only the target user or an admin may view their clinicians"
        )
    target_user = await user_repo.get_by_model_id(User, user_id)
    if target_user is None:
        raise NotFoundError(detail=f"User {user_id} not found")
    page_number = parse_page(request)
    per_page = DEFAULT_PAGE_SIZE
    clinicians_plus_one = await repo.list_for_user(
        user_id,
        offset=offset_for(page_number, per_page),
        limit=per_page + 1,
    )
    clinicians, page = paginate(
        clinicians_plus_one, page=page_number, per_page=per_page
    )
    return {
        "request": request,
        "target_user": target_user,
        "clinicians": clinicians,
        "is_self": user_id == requesting_user.id,
        "current_user": requesting_user,
        "pager": Pager(page=page, base_query=base_query(request)),
    }


async def handle_set_license_attestation(
    clinician_id: UUID,
    licensure_id: UUID,
    payload: BaseModel,
    repo: ClinicianRepository,
    verification_repo: VerificationRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
):
    """State-axis handler for `PUT /clinicians/{clinician_id}/licensures/{licensure_id}/attestation`.

    "I attest this license is active and in good standing." Flips
    `attested_active=True` + `attested_at=NOW()`, recomputes the
    licensure's `status` from `expiration_date` + the attestation, and
    re-runs `recompute_clinician_claim` so the Claim-A denorm cache
    reflects the new state. A `Verification` event of type
    `license_attested` is appended.

    Authz: the requesting user must own the parent Clinician (or be
    admin). The licensure must belong to the URL-named clinician —
    same defense-in-depth shape the framework's generic subentity
    handlers use.

    This is the canonical consumer of `mount_state_axis` with
    `spec.parent is not None`; the path / authz / response-shape rules
    all flow from the framework's existing state-axis machinery.
    """
    # Imports kept local to keep the module's top-level import surface
    # narrow; this handler is the only caller that needs them.
    from datetime import date, datetime, timezone

    from src.domain.logic.verifications.events import (
        recompute_clinician_claim,
        record_verification_event,
    )
    from src.domain.models import ClinicianLicensure
    from src.domain.specs.clinician_licensure import LICENSURE_ENTITY
    from src.framework.access.authz.authz import is_owner_or_admin
    from src.framework.audit.core import record_audit

    clinician = await repo.get_by_model_id(Clinician, clinician_id)
    if clinician is None:
        raise NotFoundError(detail="Clinician not found")
    if not is_owner_or_admin(clinician, requesting_user):
        raise ForbiddenError(detail="Cannot attest licenses for this clinician")

    licensure = await repo.get_by_model_id(ClinicianLicensure, licensure_id)
    if licensure is None or licensure.clinician_id != clinician_id:
        raise NotFoundError(detail="Licensure not found for this clinician")

    axis = LICENSURE_ENTITY.state_axis("attestation")
    before = axis.audit_snapshot_fn(licensure)

    licensure.attested_active = True
    licensure.attested_at = datetime.now(timezone.utc)
    if licensure.expiration_date is None or licensure.expiration_date >= date.today():
        licensure.status = "active"
    else:
        licensure.status = "expired"

    # Two audit surfaces here: an audit row for the licensure-level
    # mutation (carrying `SET_LICENSE_ATTESTATION`) and a
    # `Verification` event row in the verification cluster (carrying
    # `event_type='license_attested'`). The audit row is what the
    # framework's discipline guard looks for; the Verification event
    # is the event-log entry the recompute helpers and the lapse
    # detection read.
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type=LICENSURE_ENTITY.audit.type,
        resource_id=licensure.id,
        action=axis.action,
        before=before,
        after=axis.audit_snapshot_fn(licensure),
    )
    await record_verification_event(
        verification_repo=verification_repo,
        audit_repo=audit_repo,
        subject_type="clinician",
        clinician_id=clinician.id,
        event_type="license_attested",
        status="verified",
        evidence={
            "licensure_id": str(licensure.id),
            "license_type": licensure.license_type,
            "issuing_state": licensure.issuing_state,
        },
        actor_id=requesting_user.id,
    )
    recompute_clinician_claim(clinician)
    await repo.session.commit()
    return licensure


async def handle_set_clinician_verification_state(
    clinician_id: UUID,
    payload: BaseModel,
    repo: ClinicianRepository,
    verification_repo: VerificationRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
):
    """Admin-only state-axis handler for
    `PUT /clinicians/{id}/verification`.

    Forces `Clinician.npi_match_status` to the supplied state without
    going through the NPPES pipeline. Three valid transitions:

    - **`matched`** — admin accepts a row the worker landed as
      `mismatch`. Sets `npi_verified_at=NOW()`, recomputes the Claim-A
      cache (which sets `verified_at` + `ever_verified_at`).
    - **`mismatch`** — admin explicitly rejects (e.g. after manual
      NPPES audit). Row stays out of the worker queue.
    - **`pending`** — admin re-queues the row. Clears
      `npi_verified_at` so the worker treats the next attempt as
      fresh.

    The cache recompute always runs; the audit row carries
    `SET_CLINICIAN_VERIFICATION_STATE` so the override is
    distinguishable from worker-driven `npi_resolved` events in the
    audit trail. A `Verification` event of type `admin_verify` /
    `admin_suspend` is appended for the matched / mismatch
    transitions so the event log records who closed the loop.
    """
    from datetime import datetime, timezone

    from src.domain.logic.verifications.events import record_verification_event
    from src.domain.logic.verifications.handlers import recompute_clinician_claim
    from src.domain.specs.clinician import CLINICIAN_ENTITY
    from src.framework.audit.core import record_audit

    if not requesting_user.is_superuser:
        raise ForbiddenError(
            detail="Setting clinician verification state is admin-only"
        )

    clinician = await repo.get_by_model_id(Clinician, clinician_id)
    if clinician is None:
        raise NotFoundError(detail="Clinician not found")

    axis = CLINICIAN_ENTITY.state_axis("verification")
    snapshot = axis.audit_snapshot_fn
    before = snapshot(clinician)

    target_state = payload.state
    clinician.npi_match_status = target_state
    if target_state == "matched":
        clinician.npi_verified_at = datetime.now(timezone.utc)
        verification_event: str | None = "admin_verify"
    elif target_state == "mismatch":
        verification_event = "admin_suspend"
    else:
        # `pending` — clear the verified timestamp so the worker's
        # next attempt isn't gated on the stale value.
        clinician.npi_verified_at = None
        verification_event = None

    recompute_clinician_claim(clinician)

    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type=CLINICIAN_ENTITY.audit.type,
        resource_id=clinician.id,
        action=axis.action,
        before=before,
        after=snapshot(clinician),
    )
    if verification_event is not None:
        await record_verification_event(
            verification_repo=verification_repo,
            audit_repo=audit_repo,
            subject_type="clinician",
            clinician_id=clinician.id,
            event_type=verification_event,
            status="verified" if target_state == "matched" else "failed",
            evidence={"actor_id": str(requesting_user.id)},
            actor_id=requesting_user.id,
        )
    await repo.session.commit()
    logger.info(
        "clinician.verification: id=%s state=%s actor=%s",
        clinician.id,
        target_state,
        requesting_user.id,
    )
    return clinician


# --- Sub-resource list handlers ------------------------------------------
#
# `GET /clinicians/{clinician_id}/<sub>` — one dedicated list page per
# clinician sub-resource (practices, licensures, educations, certifications).
# The sub-resources are already eager-loaded on the clinician via
# `relationship(lazy="selectin")`, so each handler just loads the parent
# and returns its rows. The framework's `mount_related_list` auto-injects
# the breadcrumb chain because `CLINICIAN_ENTITY.display_label_fn` is set.
# The repo arg is the child's repo (per `RelatedListSubresource`
# convention); the credentials all use `ClinicianRepository`, and
# affiliations use `ClinicianAffiliationRepository` — neither is queried
# here since the data is already on the parent, but the synth layer
# requires the param to satisfy the spec contract.


async def _list_clinician_subresource_context(
    *,
    request: Request,
    clinician_id: UUID,
    clinician_repo: ClinicianRepository,
    attr: str,
) -> dict[str, Any]:
    """Shared list-handler body for clinician sub-resources. Loads the
    parent clinician (404 on miss) and returns its eager-loaded
    sub-resource list under ``rows``."""
    clinician = await clinician_repo.get_by_model_id(Clinician, clinician_id)
    if clinician is None:
        raise NotFoundError(detail=f"Clinician {clinician_id} not found")
    return {
        "request": request,
        "clinician": clinician,
        "rows": getattr(clinician, attr),
    }


async def handle_list_clinician_affiliations(
    request: Request,
    clinician_id: UUID,
    repo: ClinicianAffiliationRepository,
    clinician_repo: ClinicianRepository,
    organization_repo: OrganizationRepository,
    requesting_user: User,
) -> dict[str, Any]:
    """List the clinician's `ClinicianAffiliation` rows. The inline
    add-practice form on this page renders an Org `<select>`, so the
    handler also pulls the requesting user's visible Orgs into context
    (same source as the clinician edit page's `form_extras`)."""
    context = await _list_clinician_subresource_context(
        request=request,
        clinician_id=clinician_id,
        clinician_repo=clinician_repo,
        attr="clinician_affiliations",
    )
    context["orgs"] = await list_visible_to(
        organization_repo, requesting_user, Organization
    )
    return context


async def handle_list_clinician_licensures(
    request: Request,
    clinician_id: UUID,
    repo: ClinicianRepository,
    clinician_repo: ClinicianRepository,
    requesting_user: User,
) -> dict[str, Any]:
    return await _list_clinician_subresource_context(
        request=request,
        clinician_id=clinician_id,
        clinician_repo=clinician_repo,
        attr="licensures",
    )


async def handle_list_clinician_educations(
    request: Request,
    clinician_id: UUID,
    repo: ClinicianRepository,
    clinician_repo: ClinicianRepository,
    requesting_user: User,
) -> dict[str, Any]:
    return await _list_clinician_subresource_context(
        request=request,
        clinician_id=clinician_id,
        clinician_repo=clinician_repo,
        attr="educations",
    )


async def handle_list_clinician_certifications(
    request: Request,
    clinician_id: UUID,
    repo: ClinicianRepository,
    clinician_repo: ClinicianRepository,
    requesting_user: User,
) -> dict[str, Any]:
    return await _list_clinician_subresource_context(
        request=request,
        clinician_id=clinician_id,
        clinician_repo=clinician_repo,
        attr="certifications",
    )
