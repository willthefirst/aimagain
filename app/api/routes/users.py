import logging

from fastapi import APIRouter, Depends, Request

# Import common utilities
from app.api.common import APIResponse, BaseRouter, InternalServerError
from app.auth_config import current_active_user
from app.logic.user_processing import handle_list_users
from app.models import User
from app.repositories.dependencies import get_user_repository
from app.repositories.user_repository import UserRepository

# Corrected instantiation pattern:
# 1. Create the APIRouter. This instance will be imported and included in the main FastAPI app.
users_router_instance = APIRouter()

# 2. Create a BaseRouter helper, passing it the actual APIRouter instance and default tags.
router = BaseRouter(router=users_router_instance, default_tags=["users"])

logger = logging.getLogger(__name__)


@router.get("/users")
async def list_users(
    request: Request,
    user_repo: UserRepository = Depends(get_user_repository),
    user: User = Depends(current_active_user),
    participated_with: str | None = None,
):
    """Provides an HTML page listing registered users.
    Can be filtered to users participated with the current user.
    Requires authentication.
    Uses a logic handler to fetch and prepare user data.
    """
    context = await handle_list_users(
        request=request,
        user_repo=user_repo,
        requesting_user=user,
        participated_with_filter=participated_with,
    )
    # Use APIResponse.html_response helper
    # Ensure the context includes 'request' for TemplateResponse
    if "request" not in context:
        context["request"] = request
    return APIResponse.html_response(
        template_name="users/list.html", context=context, request=request
    )


# In main.py or similar, you would import and include users_router_instance:
# from app.api.routes.users import users_router_instance
# app.include_router(users_router_instance) # Potentially with a prefix if not set on APIRouter directly
