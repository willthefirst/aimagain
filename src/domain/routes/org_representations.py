"""Route mount for `OrgRepresentation` — User↔Org authority (Claim B).

`mount_entity(ORG_REPRESENTATION_ENTITY)` mounts the framework's
generic update / delete / state-axis handlers per the spec. POST
`/org_representations` is bespoke (the spec opts out of the generic
create via `routes.create=False`) so the per-authority-method dispatch
in `handle_create_org_representation` owns row construction — every
row gets the right initial `authority_status` instead of always
landing at `'pending'`.
"""

from typing import Any

from fastapi import Depends, status

from src.auth_config import current_active_user
from src.domain.logic.org_representations.handlers import (
    handle_create_org_representation,
)
from src.domain.logic.org_representations.repository import (
    OrgRepresentationRepository,
    get_org_representation_repository,
)
from src.domain.logic.org_representations.schema import OrgRepresentationCreate
from src.domain.logic.verifications.repository import (
    VerificationRepository,
    get_verification_repository,
)
from src.domain.models import User
from src.domain.specs.org_representation import ORG_REPRESENTATION_ENTITY
from src.framework import register_entity
from src.framework.audit.repository import AuditRepository
from src.framework.dispatch.resource_routes import mount_entity
from src.framework.persistence.dependencies import get_audit_repository

router = register_entity(ORG_REPRESENTATION_ENTITY)


@router.post(
    "/org_representations",
    status_code=status.HTTP_201_CREATED,
    name="org_representations:create",
)
async def create_org_representation(
    payload: OrgRepresentationCreate,
    repo: OrgRepresentationRepository = Depends(get_org_representation_repository),
    verification_repo: VerificationRepository = Depends(get_verification_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    requesting_user: User = Depends(current_active_user),
) -> dict[str, Any]:
    """POST `/org_representations` — bespoke handler that dispatches on
    `payload.authority_method`. See
    `src.domain.logic.org_representations.handlers.handle_create_org_representation`
    for the per-method contract.
    """
    new_row = await handle_create_org_representation(
        payload=payload,
        repo=repo,
        verification_repo=verification_repo,
        audit_repo=audit_repo,
        requesting_user=requesting_user,
    )
    return {
        "id": str(new_row.id),
        "authority_status": new_row.authority_status,
    }


mount_entity(router, ORG_REPRESENTATION_ENTITY)
