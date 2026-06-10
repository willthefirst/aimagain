"""Read-only routes for `/users/me/access` — the current user's capability posture.

  GET /users/me/access                         all named capabilities, granted/denied
  GET /users/me/access/capabilities/{name}     requirement tree for one capability

Derived read views only — no stored rows, no write operations. Fix links on
unmet Condition nodes dispatch outward to the canonical resources that change
the underlying state.
"""

from fastapi import APIRouter

from src.domain.logic import capabilities
from src.framework.access.capabilities.capabilities import mount_capability_routes

access_router = APIRouter(prefix="/users/me/access", tags=["access"])

_CHECKS = {
    "provider-network": capabilities.check_network,
    "program-intake": capabilities.check_program_intake,
}

mount_capability_routes(access_router, _CHECKS)
