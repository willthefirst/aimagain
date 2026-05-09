import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.api.common import BaseRouter
from src.api.common.resource_routes import (
    ResourceSpec,
    mount_delete,
    mount_detail,
    mount_list,
    mount_related_list,
)
from src.api.routes.providers import PROVIDER_SPEC
from src.auth_config import current_active_user, current_admin_user
from src.logic.providers.provider_processing import handle_list_user_providers
from src.logic.users.user_processing import (
    USER,
    handle_delete_user,
    handle_get_user_detail,
    handle_list_users,
    handle_set_user_activation,
)
from src.models import User
from src.repositories.audit_repository import AuditRepository
from src.repositories.dependencies import (
    get_audit_repository,
    get_provider_repository,
    get_user_repository,
)
from src.repositories.users.user_repository import UserRepository
from src.schemas.users.user import UserActivationUpdate

users_api_router = APIRouter(prefix="/users")
router = BaseRouter(router=users_api_router, default_tags=["users"])
logger = logging.getLogger(__name__)


USER_SPEC = ResourceSpec(
    collection="users",
    id_param="user_id",
    repo_dep=get_user_repository,
    audit_resource=USER,
    read_user_dep=current_active_user,
    write_user_dep=current_admin_user,
    list_template="users/list.html",
    detail_template="users/detail.html",
)


# GET /users
mount_list(router, USER_SPEC, handler=handle_list_users)
# GET /users/{user_id} AND GET /users/me — `singleton_alias=("me", session_dep)`
# also mounts `/users/me`, which sources the id from the session. Same
# template, same handler — `me` is purely an id-derivation convenience.
# `handle_get_user_detail` takes the provider repo to embed the
# owned-providers list; the mount injects it under `provider_repo`
# (derived from `get_provider_repository`).
mount_detail(
    router,
    USER_SPEC,
    handler=handle_get_user_detail,
    extra_repo_deps=(get_provider_repository,),
    singleton_alias=("me", current_active_user),
)


# GET /users/{user_id}/providers AND GET /users/me/providers — related-list,
# scoped to the parent user. `singleton_alias=` plumbs the same handler at
# the `/me/...` path with the parent id sourced from the session. Self-or-admin
# auth lives inside the handler. Template is in the parent's namespace
# (users/providers_list.html), not the child's, since the page is *about a user*.
mount_related_list(
    router,
    parent_spec=USER_SPEC,
    child_spec=PROVIDER_SPEC,
    handler=handle_list_user_providers,
    template="users/providers_list.html",
    extra_repo_deps=(get_user_repository,),
    singleton_alias=("me", current_active_user),
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
        repo=user_repo,
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


# DELETE /users/{user_id} is mounted via the unified ResourceSpec grammar.
# Admin-only: hard-delete a user. The handler uses `mutate(verb="delete")`
# so the audit row + commit are owned by the context manager.
mount_delete(
    router,
    USER_SPEC,
    handler=handle_delete_user,
    audit_repo_dep=get_audit_repository,
)
