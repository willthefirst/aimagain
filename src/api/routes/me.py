import logging

from fastapi import APIRouter, Depends, Request

from src.api.common import APIResponse, BaseRouter
from src.auth_config import current_active_user
from src.logic.providers.provider_processing import handle_list_user_providers
from src.models import User
from src.repositories.dependencies import get_provider_repository, get_user_repository
from src.repositories.providers.provider_repository import ProviderRepository
from src.repositories.users.user_repository import UserRepository
from src.schemas.users.user import UserRead

logger = logging.getLogger(__name__)
me_router_instance = APIRouter(prefix="/users/me")
router = BaseRouter(router=me_router_instance, default_tags=["me"])


@router.get("", response_model=UserRead)
async def get_me(
    user: User = Depends(current_active_user),
):
    """Returns the current authenticated user as JSON.

    Replaces the fastapi-users built-in `/users/me` so the `/users` resource
    is owned end-to-end by this app (the built-in router also defined a
    conflicting `/users/{id}` that fought with our HTML detail page).
    """
    return user


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


@router.get("/providers")
async def list_my_providers(
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    user: User = Depends(current_active_user),
):
    """Renders the current user's provider list. Convenience alias
    for `GET /users/{requesting_user.id}/providers`."""
    context = await handle_list_user_providers(
        request=request,
        user_id=user.id,
        repo=repo,
        user_repo=user_repo,
        requesting_user=user,
    )
    return APIResponse.html_response(
        template_name="users/providers_list.html",
        context=context,
        request=request,
    )
