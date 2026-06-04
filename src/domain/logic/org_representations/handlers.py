"""Handlers for `OrgRepresentation` create dispatch + state-axis.

The create path uses the framework's generic factory plus two spec
hooks:

1. **`validate_org_representation_payload`** — `payload_authz_path`.
   Runs after `write_authz`, before model construction. Enforces the
   per-`authority_method` preconditions:

   - ``authorized_official`` — NPPES Authorized-Official name-match.
     The org's cached `authorized_official_name` is compared to the
     requesting user's verified `Clinician` legal name; no match → 400.
   - ``rep_approval`` — requires the requesting user to be an existing
     verified rep of the org (admin bypass).
   - ``domain_email`` — v1 stub: 400 "not yet enabled".
   - ``admin_review`` — no precondition; passes through.

   Also enforces the cross-cutting "can't create for someone else"
   rule.

2. **`after_create_org_representation`** — `after_create_path`. Runs
   after persistence, inside the framework's `mutate(...)` transaction
   so its mutations land in the audit `after` snapshot. Per
   `authority_method`:

   - ``authorized_official`` / ``rep_approval`` → flip
     `authority_status='verified'` (+ `approved_by` for rep_approval),
     append a `Verification` event of type `authority_proven`.
   - ``admin_review`` → leave at `pending` (default).

The two-hook split keeps validation and side effects separate, and
both run from the generic create path — no bespoke route handler
needed.

3. **`handle_set_org_representation_authority`** — PUT
   `/org_representations/{id}/authority`. Admin override flips
   `authority_status`. Unchanged.
"""

import logging
from uuid import UUID

from pydantic import BaseModel

from src.domain.logic.org_representations.repository import (
    OrgRepresentationRepository,
)
from src.domain.logic.org_representations.schema import (
    OrgRepresentationAuthorityUpdate,
)
from src.domain.logic.verifications.events import record_verification_event
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.logic.verifications.scoring import _name_similarity
from src.domain.models import Organization, OrgRepresentation, User
from src.domain.specs.org_representation import ORG_REPRESENTATION_ENTITY
from src.framework.audit.core import record_audit
from src.framework.audit.repository import AuditRepository
from src.framework.http.exceptions import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
)

logger = logging.getLogger(__name__)

# Same threshold the clinician-side NPPES name match uses.
_AO_NAME_MATCH_THRESHOLD = 0.80


async def grant_owner_representation(
    *,
    user_id: UUID,
    org_id: UUID,
    org_rep_repo: OrgRepresentationRepository,
) -> OrgRepresentation:
    """Grant the user who just created an org an immediately-verified
    *owner* representation.

    Self-creating an org — a clinician's solo-practice auto-org, or a
    self-service org registration — is itself proof of authority, so the
    owner skips the `pending` review the `authorized_official` /
    `rep_approval` methods go through: `authority_status='verified'` from
    the start. `authority_method='admin_review'` records that the grant
    rests on the create action rather than an external proof.

    Shared by the clinician solo-practice create path
    (`_assert_clinician_payload_org_ownership`) and the organization
    create path so the two can't drift on the owner-grant shape.
    """
    rep = OrgRepresentation(
        user_id=user_id,
        org_id=org_id,
        role="owner",
        authority_method="admin_review",
        authority_status="verified",
    )
    return await org_rep_repo.create(rep)


def _verified_clinician_full_name(user: User) -> str | None:
    """First-verified Clinician's `<first> <last>` form, or None if the
    user has no `clinician_verified=True` row with both names."""
    for c in getattr(user, "clinicians", None) or ():
        if not getattr(c, "clinician_verified", False):
            continue
        first = (c.first_name or "").strip()
        last = (c.last_name or "").strip()
        if first and last:
            return f"{first} {last}"
    return None


async def validate_org_representation_payload(
    *,
    payload: BaseModel,
    requesting_user: User,
    org_rep_repo: OrgRepresentationRepository,
) -> None:
    """`payload_authz_path` target — per-`authority_method` precondition
    checks. Raises `ForbiddenError` / `BadRequestError` / `NotFoundError`
    on rejection; returns `None` on success.

    Loads the target Organization here (not in `after_create`) so the
    AO name-match runs before the row is persisted — fails fast.
    """
    if payload.user_id != requesting_user.id and not requesting_user.is_superuser:
        raise ForbiddenError(
            detail="Cannot create an org representation for another user"
        )

    org = await org_rep_repo.get_by_model_id(Organization, payload.org_id)
    if org is None:
        raise NotFoundError(detail="Organization not found")

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

    elif payload.authority_method == "domain_email":
        raise BadRequestError(
            detail=(
                "The domain_email authority path is not yet enabled. "
                "Use authorized_official, rep_approval, or admin_review."
            )
        )

    elif payload.authority_method == "rep_approval":
        approver_reps = await org_rep_repo.list_verified_for_org(payload.org_id)
        if not any(r.user_id == requesting_user.id for r in approver_reps):
            if not requesting_user.is_superuser:
                raise ForbiddenError(
                    detail=(
                        "The rep_approval path requires an existing verified "
                        "representative of this organization to approve the "
                        "new rep."
                    )
                )

    # `admin_review` passes through; the row will land at pending.


async def after_create_org_representation(
    *,
    row: OrgRepresentation,
    payload: BaseModel,
    requesting_user: User,
    verification_repo: VerificationRepository,
    audit_repo_dep: AuditRepository,
) -> None:
    """`after_create_path` target — post-persist dispatch on
    `payload.authority_method`. Mutates the row's `authority_status`
    and (for `rep_approval`) `approved_by`; appends a `Verification`
    event for the auto-verified paths.

    Runs inside the framework's `mutate(...)` create transaction. Row
    mutations here land in the audit `after` snapshot; the
    `Verification` event lands in the same transaction so the audit +
    verification rows commit atomically.

    The hook DOES NOT re-run validation — that's
    `validate_org_representation_payload`'s job. By the time we get
    here, the payload is known-good.
    """
    if payload.authority_method == "authorized_official":
        row.authority_status = "verified"
        verification_event = "authority_proven"
    elif payload.authority_method == "rep_approval":
        row.authority_status = "verified"
        row.approved_by = requesting_user.id
        verification_event = "authority_proven"
    else:
        # `admin_review` → leave at the default `pending`.
        verification_event = None

    if verification_event is not None:
        await record_verification_event(
            verification_repo=verification_repo,
            audit_repo=audit_repo_dep,
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
    logger.info(
        "org_representation.after_create: id=%s user=%s org=%s method=%s status=%s",
        row.id,
        payload.user_id,
        payload.org_id,
        payload.authority_method,
        row.authority_status,
    )


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
