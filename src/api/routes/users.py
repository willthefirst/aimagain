import logging

from fastapi import APIRouter

from src.api.common import BaseRouter
from src.api.common.resource_routes import (
    mount_delete,
    mount_detail,
    mount_list,
    mount_related_list,
    mount_state_axis,
)
from src.api.common.specs.user import USER_ENTITY
from src.auth_config import current_active_user
from src.logic.providers.provider_processing import handle_list_user_providers
from src.logic.users.user_processing import (
    handle_delete_user,
    handle_get_user_detail,
    handle_list_users,
    handle_set_user_activation,
)

users_api_router = APIRouter(prefix="/users")
router = BaseRouter(router=users_api_router, default_tags=["users"])
logger = logging.getLogger(__name__)


# Derive the mount-time `ResourceSpec` from the entity spec. `USER_ENTITY`
# is the single declaration of identity (audit binding, private-field
# visibility, route flags, state-axis shape, subresources, templates);
# `mount_*` helpers still consume `ResourceSpec`, so we bridge.
USER_SPEC = USER_ENTITY.to_resource_spec()


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
# scoped to the parent user. The subresource shape (child spec, template,
# `/me` alias) is declared once on `USER_ENTITY.subresources`; the mount
# call reads from there so the spec stays the single source of truth.
_providers_subresource = USER_ENTITY.subresources[0]
mount_related_list(
    router,
    parent_spec=USER_SPEC,
    child_spec=_providers_subresource.child_spec,
    handler=handle_list_user_providers,
    template=_providers_subresource.template,
    singleton_alias=_providers_subresource.singleton_alias,
)


# PUT /users/{user_id}/activation — admin-only state-axis flip.
# Axis shape (name, body schema, response projection) is declared on
# `USER_ENTITY.state_axes`; the handler is bound here because phase 1
# does not carry handler references on the spec (see the docstring on
# `src/api/common/entity_spec.py` for the import-direction rationale).
_activation_axis = USER_ENTITY.state_axis("activation")
mount_state_axis(
    router,
    USER_SPEC,
    handler=handle_set_user_activation,
    axis_name=_activation_axis.name,
    body_schema=_activation_axis.body_schema,
    response_to_dict=_activation_axis.response_to_dict,
)


# DELETE /users/{user_id} is mounted via the unified ResourceSpec grammar.
# Admin-only: hard-delete a user. The handler uses `mutate(verb="delete")`
# so the audit row + commit are owned by the context manager.
mount_delete(
    router,
    USER_SPEC,
    handler=handle_delete_user,
)
