"""Bespoke router for the Profile Hub (`/profile`).

The hub is one component with four modes — setup / manage / add-a-claim
/ re-verify — and onboarding IS this hub in setup mode (no separate
wizard). Mode is a pure function of the requesting user's claim state;
see `src.domain.logic.profile.handlers.resolve_profile_mode`.

The hub is intentionally **not** mounted as a generic EntitySpec: it's
not a CRUD resource (no id in the URL, no list/detail surface), and
overloading the `/users/{id}` detail page with mode-dispatch would
make the user entity ungeneric. The bespoke shape matches
`auth_pages` / `verifications` (see `routes/README.md` § "Bespoke
routes").
"""

from typing import Any

from fastapi import APIRouter, Depends, Request

from src.auth_config import current_active_user
from src.domain.logic.profile.handlers import build_profile_context
from src.domain.models import User
from src.framework.http.responses import APIResponse

profile_pages_router = APIRouter(tags=["Profile"])


@profile_pages_router.get("/profile", name="profile:hub")
async def profile_hub(
    request: Request,
    requesting_user: User = Depends(current_active_user),
    intent: str | None = None,
) -> Any:
    """Render the profile hub. `intent=add_claim` (set by the
    "Add a capability" CTA) lands the user in `add-a-claim` mode when
    they already hold at least one claim; otherwise mode is derived
    purely from the claim state.
    """
    context = build_profile_context(requesting_user, intent=intent)
    return APIResponse.html_response(
        "profile/hub.html",
        context,
        request,
        current_user=requesting_user,
    )
