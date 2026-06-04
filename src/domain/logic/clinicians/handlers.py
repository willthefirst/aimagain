"""Clinician-directory orchestration handlers."""

import logging
from typing import Any
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel

from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.favorites.repository import UserFavoriteRepository
from src.domain.logic.org_representations.repository import (
    OrgRepresentationRepository,
)
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.users.repository import UserRepository
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import (
    Clinician,
    Organization,
    User,
)
from src.framework.audit.repository import AuditRepository
from src.framework.authz import assert_fk_ownership, list_visible_to
from src.framework.dispatch.pagination import (
    DEFAULT_PAGE_SIZE,
    Pager,
    base_query,
    offset_for,
    paginate,
    parse_page,
)
from src.framework.http.exceptions import ForbiddenError, NotFoundError
from src.framework.rendering.templating import set_viewer

logger = logging.getLogger(__name__)


async def after_create_clinician_verification(
    *,
    row: Clinician,
    payload: BaseModel,
    requesting_user: User,
    verification_repo: VerificationRepository,
    clinician_repo: ClinicianRepository,
    verification_audit_repo: AuditRepository,
    demo_outcome: str | None = None,
) -> None:
    """Run the NPI verification pipeline immediately after a clinician row
    is created. Produces one Verification row + audit row and writes through
    the Claim-A denorm cache, all within the same request transaction.

    `run_clinician_verification` commits internally. After that commit the
    session expires `row`'s attributes, so a `refresh` follows to keep the
    object usable for the `mutate` context manager's after-snapshot (which
    runs synchronously via Pydantic's `model_validate`).

    When `demo_outcome` is provided the caller has already verified the
    clinician is in a demo org; NPPES/OIG is skipped and the selected
    outcome is persisted directly.
    """
    import httpx

    from src.domain.logic.verifications.handlers import (
        HTTP_TIMEOUT_SECONDS,
        run_clinician_demo_verification,
        run_clinician_verification,
    )

    if demo_outcome and demo_outcome in ("verified", "needs_review", "failed"):
        await run_clinician_demo_verification(
            clinician_id=row.id,
            demo_outcome=demo_outcome,  # type: ignore[arg-type]
            verification_repo=verification_repo,
            clinician_repo=clinician_repo,
            audit_repo=verification_audit_repo,
            actor_id=requesting_user.id,
        )
    else:
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
    """
    if "npi" not in changed_fields:
        return
    await after_create_clinician_verification(
        row=row,
        payload=payload,
        requesting_user=requesting_user,
        verification_repo=verification_repo,
        clinician_repo=clinician_repo,
        verification_audit_repo=verification_audit_repo,
    )


async def _assert_clinician_payload_org_ownership(
    *,
    payload: BaseModel,
    requesting_user: User,
    organization_repo: OrganizationRepository,
    org_rep_repo: OrgRepresentationRepository,
) -> Organization | None:
    """Payload authz for clinician create/update.

    Solo-practice path: when ``payload.solo_practice`` is True,
    auto-create a solo-practice Organization, patch ``payload.org_id``,
    grant the user an immediately-verified owner ``OrgRepresentation`` over
    it, and return the created org. Wiring the owner rep here (rather than
    in each caller) keeps the canonical ``POST /clinicians`` solo path and
    the onboarding hub on the same owner-grant — previously only the hub
    created the rep, so a solo clinician made via ``/clinicians/form`` got
    an org with no authority over it.
    Normal path: delegate to the framework's FK-ownership guard, return None.
    """
    from src.domain.logic.org_representations.handlers import (
        grant_owner_representation,
    )

    if getattr(payload, "solo_practice", False):
        practice_name = (getattr(payload, "practice_name", None) or "").strip()
        if not practice_name:
            first = (getattr(payload, "first_name", None) or "").strip()
            last = (getattr(payload, "last_name", None) or "").strip()
            name_parts = [p for p in (first, last) if p]
            practice_name = (
                " ".join(name_parts) if name_parts else requesting_user.username
            )
        auto_org = Organization(
            name=practice_name,
            type="solo_practice",
            owner_id=requesting_user.id,
        )
        created_org = await organization_repo.create(auto_org)
        payload.org_id = created_org.id
        await grant_owner_representation(
            user_id=requesting_user.id,
            org_id=created_org.id,
            org_rep_repo=org_rep_repo,
        )
        return created_org
    await assert_fk_ownership(
        payload=payload,
        attr="org_id",
        requesting_user=requesting_user,
        parent_repo=organization_repo,
        parent_model=Organization,
        parent_noun="Organization",
        child_noun="Clinician",
    )
    return None


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
    set_viewer(requesting_user)
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
    from src.framework.audit.core import record_audit
    from src.framework.authz import is_owner_or_admin

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
