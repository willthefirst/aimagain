"""Read-only routes for `/users/me/access` — the current user's capability posture.

  GET /users/me/access                         all named capabilities, granted/denied
  GET /users/me/access/capabilities/{name}     requirement tree for one capability

Derived read views only — no stored rows, no write operations. Fix links on
unmet Condition nodes dispatch outward to the canonical resources that change
the underlying state.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.auth_config import current_active_user
from src.domain.logic import capabilities
from src.framework.http.responses import APIResponse

access_router = APIRouter(prefix="/users/me/access", tags=["access"])

_CHECKS = {
    "network": capabilities.check_network,
}


_ACCESS_INDEX_URL = "/users/me/access"
_CAPABILITIES_URL = "/users/me/access/capabilities"
_CAPABILITY_BASE_URL = "/users/me/access/capabilities"


@access_router.get("")
async def access_index(
    request: Request,
    user=Depends(current_active_user),
):
    return APIResponse.html_response(
        template_name="users/access/index.html",
        context={
            "capabilities_url": _CAPABILITIES_URL,
        },
        request=request,
        current_user=user,
    )


@access_router.get("/capabilities")
async def capabilities_index(
    request: Request,
    user=Depends(current_active_user),
):
    checks = {name: fn(user) for name, fn in _CHECKS.items()}
    return APIResponse.html_response(
        template_name="users/access/capabilities/index.html",
        context={
            "checks": checks,
            "capability_base_url": _CAPABILITY_BASE_URL,
            "access_index_url": _ACCESS_INDEX_URL,
        },
        request=request,
        current_user=user,
    )


@access_router.get("/capabilities/{name}")
async def capability_detail(
    name: str,
    request: Request,
    user=Depends(current_active_user),
):
    fn = _CHECKS.get(name)
    if fn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    check = fn(user)
    return APIResponse.html_response(
        template_name="users/access/capabilities/detail.html",
        context={
            "check": check,
            "access_index_url": _ACCESS_INDEX_URL,
            "capabilities_url": _CAPABILITIES_URL,
        },
        request=request,
        current_user=user,
    )
