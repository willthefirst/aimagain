"""Handlers for the `OrgRepresentation` state-axis subresource.

Generic CRUD is provided by `mount_entity` via the framework's
`handle_create` / `handle_update` / `handle_delete` factories. The one
bespoke piece this cluster needs today is the **authority state axis** —
admin (or `rep_approval` approver) flipping `authority_status` without
re-PUTing the whole row, with a fresh audit entry and a Verification
event each transition.

Phase-4 extension PRs will add the per-method authority dispatch
(`authorized_official` auto-match, `rep_approval` invite/approve, etc.)
on top of the generic create path. For now `mount_entity` accepts
create payloads with any authority_method and inserts at
`authority_status='pending'` — the state axis here is the only path to
flip to `verified` / `rejected`.
"""

import logging
from uuid import UUID

from src.domain.logic.org_representations.repository import (
    OrgRepresentationRepository,
)
from src.domain.logic.org_representations.schema import (
    OrgRepresentationAuthorityUpdate,
)
from src.domain.models import OrgRepresentation, User
from src.domain.specs.org_representation import ORG_REPRESENTATION_ENTITY
from src.framework.audit.core import record_audit
from src.framework.audit.repository import AuditRepository
from src.framework.http.exceptions import ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)


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
