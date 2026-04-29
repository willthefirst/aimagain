import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from src.api.common import APIResponse, BaseRouter
from src.auth_config import current_active_user, current_admin_user
from src.logic.user_processing import (
    handle_delete_user,
    handle_get_user_detail,
    handle_list_users,
    handle_set_user_activation,
)
from src.models import User
from src.repositories.audit_repository import AuditRepository
from src.repositories.dependencies import get_audit_repository, get_user_repository
from src.repositories.user_repository import UserRepository
from src.schemas.user import UserActivationUpdate

users_api_router = APIRouter(prefix="/users")
router = BaseRouter(router=users_api_router, default_tags=["users"])
logger = logging.getLogger(__name__)


@router.get("")
async def list_users(
    request: Request,
    user_repo: UserRepository = Depends(get_user_repository),
    user: User = Depends(current_active_user),
):
    """Provides an HTML page listing registered users.
    Requires authentication.
    Uses a logic handler to fetch and prepare user data.
    """
    context = await handle_list_users(
        request=request,
        user_repo=user_repo,
        requesting_user=user,
    )
    return APIResponse.html_response(
        template_name="users/list.html", context=context, request=request
    )


@router.get("/{user_id}")
async def get_user(
    user_id: UUID,
    request: Request,
    user_repo: UserRepository = Depends(get_user_repository),
    user: User = Depends(current_active_user),
):
    """Provides an HTML detail page for a single user."""
    context = await handle_get_user_detail(
        request=request,
        user_id=user_id,
        user_repo=user_repo,
        requesting_user=user,
    )
    return APIResponse.html_response(
        template_name="users/detail.html", context=context, request=request
    )


@router.put("/{user_id}/activation")
async def set_user_activation(
    user_id: UUID,
    payload: UserActivationUpdate,
    user_repo: UserRepository = Depends(get_user_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    admin: User = Depends(current_admin_user),
):
    """Admin-only: activate or deactivate a user."""
    updated = await handle_set_user_activation(
        user_id=user_id,
        payload=payload,
        user_repo=user_repo,
        audit_repo=audit_repo,
        requesting_user=admin,
    )
    return JSONResponse(
        content={
            "id": str(updated.id),
            "username": updated.username,
            "is_active": updated.is_active,
        },
        headers={"HX-Refresh": "true"},
    )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    user_repo: UserRepository = Depends(get_user_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    admin: User = Depends(current_admin_user),
):
    """Admin-only: hard-delete a user."""
    await handle_delete_user(
        user_id=user_id,
        user_repo=user_repo,
        audit_repo=audit_repo,
        requesting_user=admin,
    )
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"HX-Redirect": "/users"},
    )
