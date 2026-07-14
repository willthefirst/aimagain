"""Bespoke read-only route for the `/admin/audit` page.

    GET /admin/audit    paginated audit log, superusers only

Derived read view over the framework-owned `audit_log` table — no
stored admin resource, no writes, no `EntitySpec` (the audit log has no
owner filter or CRUD face, so a bespoke handler is simpler than
spec-driven mounting). `current_admin_user` 403s any non-superuser
before the handler runs.

Follows the bespoke-route pattern documented in
`src/domain/routes/README.md § Bespoke routes`.
"""

from fastapi import APIRouter, Depends, Request

from src.auth_config import current_admin_user
from src.domain.models import User
from src.framework.audit.repository import AuditRepository
from src.framework.dispatch.pagination import offset_for, paginate, parse_page
from src.framework.http.responses import APIResponse
from src.framework.persistence.dependencies import get_audit_repository

admin_router = APIRouter(prefix="/admin", tags=["admin"])

# Denser than DEFAULT_PAGE_SIZE (15): audit rows are one-line log
# entries scanned in bulk, not cards browsed one at a time.
AUDIT_PAGE_SIZE = 50


@admin_router.get("/audit", name="admin:audit")
async def get_audit_log(
    request: Request,
    requesting_user: User = Depends(current_admin_user),
    audit_repo: AuditRepository = Depends(get_audit_repository),
):
    page = parse_page(request)
    rows = await audit_repo.list_all(
        offset=offset_for(page, AUDIT_PAGE_SIZE), limit=AUDIT_PAGE_SIZE + 1
    )
    rows, page_meta = paginate(rows, page=page, per_page=AUDIT_PAGE_SIZE)
    return APIResponse.html_response(
        template_name="admin/audit.html",
        context={"rows": rows, "page_meta": page_meta},
        request=request,
        current_user=requesting_user,
    )
