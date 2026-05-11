import logging

from fastapi import APIRouter

from src.api.common import BaseRouter
from src.api.common.resource_routes import mount_entity
from src.api.common.specs.user import USER_ENTITY
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


# `handle_delete_user` is bespoke (self-guard); the other handlers are
# unchanged from prior phases. `mount_entity` reads `USER_ENTITY`'s
# routes / state_axes / subresources / singleton_alias and dispatches
# to the appropriate `mount_*` helpers — collapsing what used to be
# five separate mount calls into one.
mount_entity(
    router,
    USER_ENTITY,
    handlers={
        "list": handle_list_users,
        "detail": handle_get_user_detail,
        "delete": handle_delete_user,
        # State axis (activation): action + body schema + response
        # projection all declared on `USER_ENTITY.state_axes[0]`.
        "activation": handle_set_user_activation,
        # Related-list subresource (providers); singleton-alias
        # `/users/me/providers` declared on the spec.
        "providers": handle_list_user_providers,
    },
)
