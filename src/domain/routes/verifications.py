"""Bespoke router for the verification trigger endpoint.

`Verification` has no EntitySpec — there's no public CRUD surface, the
nightly job writes most rows, and the only HTTP entry point is this
single admin-only retrigger. The bespoke shape follows `auth_pages` /
`favorites` (see `src/domain/routes/README.md` § "Bespoke routes");
wired into `src/main.py` alongside the other hand-rolled routers.

Response shape: `201 Created` with the new `Verification` row's id and
a `Location` header pointing at the (future) per-verification read
route (`/clinicians/{provider_id}/verifications/{verification_id}` —
URL family renamed in #642 PR 4; the path-param keeps its
`provider_id` kwarg name because the handler signature takes the
Provider model id and the brief explicitly excluded handler-kwarg
renames from this PR).
The read route does not yet exist; the `Location` header is still
correct per RFC 9110 — it identifies the resource, not a route that
must already be implemented — and lands the URL shape so the future
read route can fill in without breaking clients.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from src.auth_config import current_admin_user
from src.domain.logic.providers.repository import (
    ProviderRepository,
    get_provider_repository,
)
from src.domain.logic.verifications.handlers import (
    handle_create_provider_verification,
)
from src.domain.logic.verifications.repository import (
    VerificationRepository,
    get_verification_repository,
)
from src.domain.models import User
from src.framework.audit.repository import AuditRepository
from src.framework.persistence.dependencies import get_audit_repository

verifications_api_router = APIRouter(tags=["Verifications"])


@verifications_api_router.post(
    "/clinicians/{provider_id}/verifications",
    status_code=status.HTTP_201_CREATED,
    name="verifications:create",
)
async def create_provider_verification(
    provider_id: UUID,
    response: Response,
    verification_repo: VerificationRepository = Depends(get_verification_repository),
    provider_repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    requesting_user: User = Depends(current_admin_user),
) -> dict[str, str]:
    """Admin-only manual retrigger. See
    `src/domain/logic/verifications/handlers.py` for the orchestration."""
    verification = await handle_create_provider_verification(
        provider_id=provider_id,
        verification_repo=verification_repo,
        provider_repo=provider_repo,
        audit_repo=audit_repo,
        requesting_user=requesting_user,
    )
    response.headers["Location"] = (
        f"/clinicians/{provider_id}/verifications/{verification.id}"
    )
    return {"id": str(verification.id), "status": verification.status}
