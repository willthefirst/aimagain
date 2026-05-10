import logging

from fastapi import APIRouter

from src.api.common import BaseRouter
from src.api.common.resource_routes import (
    ResourceSpec,
    mount_delete,
    mount_detail,
    mount_list,
    mount_related_list,
    mount_state_axis,
)
from src.api.routes.providers import PROVIDER_SPEC
from src.auth_config import current_active_user, current_admin_user
from src.logic._authz import is_self_or_admin
from src.logic.providers.provider_processing import handle_list_user_providers
from src.logic.users.user_processing import (
    USER,
    USER_PRIVATE_FIELDS,
    handle_delete_user,
    handle_get_user_detail,
    handle_list_users,
    handle_set_user_activation,
)
from src.repositories.dependencies import get_user_repository
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
    # Field-level visibility: viewers outside `is_self_or_admin` see only
    # public fields. The same tuple + predicate are applied by
    # `project_view` inside `handle_get_user_detail`; declaring them on
    # the spec makes the gating rule readable by any future cross-layer
    # consumer (JSON endpoint, audit snapshot, OpenAPI doc). Template
    # `{% if can_view_private %}` guard remains as defense in depth.
    private_fields=USER_PRIVATE_FIELDS,
    private_field_predicate=is_self_or_admin,
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
    singleton_alias=("me", current_active_user),
)


# PUT /users/{user_id}/activation — admin-only state-axis flip.
# `response_to_dict` projects the User into the activation-axis wire shape
# (`is_active` is the field this axis can change; `id`/`username` are
# included for client-side reconciliation).
mount_state_axis(
    router,
    USER_SPEC,
    handler=handle_set_user_activation,
    axis_name="activation",
    body_schema=UserActivationUpdate,
    response_to_dict=lambda user: {
        "id": str(user.id),
        "username": user.username,
        "is_active": user.is_active,
    },
)


# DELETE /users/{user_id} is mounted via the unified ResourceSpec grammar.
# Admin-only: hard-delete a user. The handler uses `mutate(verb="delete")`
# so the audit row + commit are owned by the context manager.
mount_delete(
    router,
    USER_SPEC,
    handler=handle_delete_user,
)
