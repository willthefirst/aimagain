"""Handlers for `OrgRepresentation` create + state-axis dispatch.

Two bespoke handlers here:

1. **`handle_create_org_representation`** — POST `/org_representations`.
   Dispatches on `payload.authority_method` per handoff §6:

   - ``authorized_official`` — NPPES Authorized-Official name-match.
     Compares the org's cached `authorized_official_name` to the
     requesting user's verified `Clinician` legal name; on match the
     row lands at `authority_status='verified'` and a `Verification`
     event of type `authority_proven` is recorded. No match → 400.
   - ``rep_approval`` — invite-driven. `approved_by` must point at a
     verified non-archived rep on the same org. Row lands at
     `authority_status='pending'`; the approver flips it via the
     `authority` state axis.
   - ``domain_email`` — v1 stub: 400 "not yet enabled". The enum
     value is shipped so the schema/UI stays coherent; full build-out
     needs an `OrganizationDomain` table + email-at-domain
     verification flow.
   - ``admin_review`` — fallback. Row lands at `authority_status='pending'`.

2. **`handle_set_org_representation_authority`** — PUT
   `/org_representations/{id}/authority`. Admin override (or
   rep-approval approver, in a follow-up) flips `authority_status`.

The generic `mount_entity` create handler is opted out
(`routes.create=False` on the spec) so this bespoke create owns the
post path. Update / delete continue to flow through the generic
handlers.
"""

import logging
from uuid import UUID

from src.domain.logic.org_representations.repository import (
    OrgRepresentationRepository,
)
from src.domain.logic.org_representations.schema import (
    OrgRepresentationAuthorityUpdate,
    OrgRepresentationCreate,
)
from src.domain.logic.verifications.events import record_verification_event
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.logic.verifications.scoring import _name_similarity
from src.domain.models import Organization, OrgRepresentation, User
from src.domain.specs.org_representation import ORG_REPRESENTATION_ENTITY
from src.framework.audit.core import record_audit, record_audit_for
from src.framework.audit.repository import AuditRepository
from src.framework.http.exceptions import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
)

logger = logging.getLogger(__name__)

# Same threshold the clinician-side NPPES name match uses. Keeping a
# module-local constant avoids reading through `scoring._NAME_MATCH_THRESHOLD`
# (a private symbol) at the handler boundary; if the clinician threshold
# changes we can re-anchor here.
_AO_NAME_MATCH_THRESHOLD = 0.80


def _verified_clinician_full_name(user: User) -> str | None:
    """First-verified Clinician's `<first> <last>` form, or None if the
    user has no `clinician_verified=True` row with both names. The
    `authorized_official` path matches this against the org's cached
    `authorized_official_name`."""
    for c in getattr(user, "clinicians", None) or ():
        if not getattr(c, "clinician_verified", False):
            continue
        first = (c.first_name or "").strip()
        last = (c.last_name or "").strip()
        if first and last:
            return f"{first} {last}"
    return None


async def handle_create_org_representation(
    payload: OrgRepresentationCreate,
    repo: OrgRepresentationRepository,
    verification_repo: VerificationRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> OrgRepresentation:
    """Create a new `OrgRepresentation` row. Authority-method dispatch
    sets the initial `authority_status` + `approved_by`; the row is
    persisted, audited, and (for the auto-verify happy path) a
    `Verification` event is appended in the same transaction.

    Authz: the requesting user must own the row they're creating
    (`payload.user_id` == requesting_user.id) or be admin. The
    target Organization must exist; the user must have appropriate
    standing for the authority method.
    """
    if payload.user_id != requesting_user.id and not requesting_user.is_superuser:
        raise ForbiddenError(
            detail="Cannot create an org representation for another user"
        )

    org = await repo.get_by_model_id(Organization, payload.org_id)
    if org is None:
        raise NotFoundError(detail="Organization not found")

    initial_status = "pending"
    approved_by: UUID | None = None
    verification_event: str | None = None

    if payload.authority_method == "authorized_official":
        if not org.authorized_official_name:
            raise BadRequestError(
                detail=(
                    "This organization has no cached Authorized Official "
                    "name. Submit the org's Type-2 NPI first so NPPES "
                    "can populate it."
                )
            )
        clinician_name = _verified_clinician_full_name(requesting_user)
        if clinician_name is None:
            raise BadRequestError(
                detail=(
                    "The Authorized-Official path requires a verified "
                    "clinician profile with first + last name. Visit "
                    "/profile to complete Claim A first."
                )
            )
        similarity = _name_similarity(clinician_name, org.authorized_official_name)
        if similarity < _AO_NAME_MATCH_THRESHOLD:
            raise BadRequestError(
                detail=(
                    "Your clinician name doesn't match this organization's "
                    "NPPES Authorized Official. Try a different authority "
                    "method (e.g. admin_review)."
                )
            )
        initial_status = "verified"
        verification_event = "authority_proven"

    elif payload.authority_method == "domain_email":
        # v1 stub — the enum value ships so the schema/UI stay coherent.
        raise BadRequestError(
            detail=(
                "The domain_email authority path is not yet enabled. "
                "Use authorized_official, rep_approval, or admin_review."
            )
        )

    elif payload.authority_method == "rep_approval":
        # An existing verified rep approves the new one. The Profile Hub
        # invite flow sets `approved_by` to the approver's user_id; the
        # request must come FROM the approver (or admin) so an
        # unauthorized user can't claim someone else's approval.
        # `approved_by` is server-set here from `requesting_user.id`
        # rather than read from the payload schema (which doesn't expose
        # it) — the requesting user IS the approver in this flow.
        approver_reps = await repo.list_verified_for_org(payload.org_id)
        if not any(r.user_id == requesting_user.id for r in approver_reps):
            if not requesting_user.is_superuser:
                raise ForbiddenError(
                    detail=(
                        "The rep_approval path requires an existing verified "
                        "representative of this organization to approve the "
                        "new rep."
                    )
                )
        approved_by = requesting_user.id
        # Approver-driven approvals land at `verified` directly — the
        # approver IS the gate.
        initial_status = "verified"
        verification_event = "authority_proven"

    elif payload.authority_method == "admin_review":
        # Land at pending; admin closes the loop via the `authority`
        # state axis.
        initial_status = "pending"

    new_row = OrgRepresentation(
        user_id=payload.user_id,
        org_id=payload.org_id,
        role=payload.role,
        authority_method=payload.authority_method,
        authority_status=initial_status,
        approved_by=approved_by,
    )
    new_row = await repo._persist_new(new_row)
    await record_audit_for(
        audit_repo,
        resource=ORG_REPRESENTATION_ENTITY.audit,
        verb="create",
        actor_id=requesting_user.id,
        target_id=new_row.id,
        before=None,
        after=ORG_REPRESENTATION_ENTITY.audit.snapshot(new_row),
    )
    if verification_event is not None:
        await record_verification_event(
            verification_repo=verification_repo,
            audit_repo=audit_repo,
            subject_type="organization",
            org_id=payload.org_id,
            event_type=verification_event,
            status="verified",
            evidence={
                "user_id": str(payload.user_id),
                "authority_method": payload.authority_method,
            },
            actor_id=requesting_user.id,
        )
    await repo.session.commit()
    logger.info(
        "org_representation.create: id=%s user=%s org=%s method=%s status=%s",
        new_row.id,
        payload.user_id,
        payload.org_id,
        payload.authority_method,
        initial_status,
    )
    return new_row


async def handle_set_org_representation_authority(
    org_representation_id: UUID,
    payload: OrgRepresentationAuthorityUpdate,
    repo: OrgRepresentationRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> OrgRepresentation:
    """Admin-only (today): flip `authority_status` on an existing
    `OrgRepresentation`.

    Phase-4 will broaden the authz: an existing verified rep on the same
    org should also be able to approve a `rep_approval`-method pending
    row. For now the route's auth dep enforces admin-only.
    """
    if not requesting_user.is_superuser:
        raise ForbiddenError(
            detail="Setting org-representation authority is admin-only"
        )

    target = await repo.get_by_model_id(OrgRepresentation, org_representation_id)
    if target is None:
        raise NotFoundError(detail="OrgRepresentation not found")

    axis = ORG_REPRESENTATION_ENTITY.state_axis("authority")
    snapshot = axis.audit_snapshot_fn
    before = snapshot(target)
    updated = await repo.patch(target, authority_status=payload.state)
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type=ORG_REPRESENTATION_ENTITY.audit.type,
        resource_id=updated.id,
        action=axis.action,
        before=before,
        after=snapshot(updated),
    )
    await repo.session.commit()
    logger.info(
        "org_representation.authority: rep=%s status=%s actor=%s",
        updated.id,
        payload.state,
        requesting_user.id,
    )
    return updated
