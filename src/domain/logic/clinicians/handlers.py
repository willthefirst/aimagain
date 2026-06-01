"""Clinician-directory orchestration handlers."""

import logging
from typing import Any
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel

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


async def _assert_clinician_payload_org_ownership(
    *,
    payload: BaseModel,
    requesting_user: User,
    organization_repo: OrganizationRepository,
) -> None:
    """Payload authz for clinician create/update.

    Solo-practice path: when ``payload.solo_practice`` is True,
    auto-create a solo-practice Organization and patch ``payload.org_id``.
    Normal path: delegate to the framework's FK-ownership guard.
    """
    if getattr(payload, "solo_practice", False):
        first = (getattr(payload, "first_name", None) or "").strip()
        last = (getattr(payload, "last_name", None) or "").strip()
        name_parts = [p for p in (first, last) if p]
        org_name = " ".join(name_parts) if name_parts else requesting_user.username
        auto_org = Organization(
            name=org_name,
            type="solo_practice",
            owner_id=requesting_user.id,
        )
        created_org = await organization_repo.create(auto_org)
        payload.org_id = created_org.id
        return
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
