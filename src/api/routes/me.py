import logging

from fastapi import APIRouter, Depends, Request

from src.api.common import APIResponse, BaseRouter
from src.auth_config import current_active_user
from src.models import User

logger = logging.getLogger(__name__)
me_router_instance = APIRouter(prefix="/users/me")
router = BaseRouter(router=me_router_instance, default_tags=["me"])


@router.get("/profile")
async def get_my_profile(
    request: Request,
    user: User = Depends(current_active_user),
):
    """Displays the current user's profile page."""
    return APIResponse.html_response(
        template_name="me/profile.html",
        context={"user": user},
        request=request,
    )
