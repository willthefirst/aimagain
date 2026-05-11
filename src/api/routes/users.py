import logging

from fastapi import APIRouter

from src.api.common import BaseRouter
from src.api.common.resource_routes import mount_entity
from src.api.common.specs.user import USER_ENTITY
from src.logic.providers.provider_processing import handle_list_user_providers
from src.logic.users.user_processing import (
    handle_delete_user,
    handle_list_users,
    handle_set_user_activation,
    user_detail_extras,
)
from src.repositories.providers.provider_repository import ProviderRepository

users_api_router = APIRouter(prefix="/users")
router = BaseRouter(router=users_api_router, default_tags=["users"])
logger = logging.getLogger(__name__)


# `handle_delete_user` is bespoke (self-guard); the detail handler is
# factory-built but takes a per-viewer `user_detail_extras` callable
# (loads owned providers + projects `target_user` via
# `USER_ENTITY.private_fields`). The extras live at the call site
# rather than on the spec because `user_detail_extras` itself imports
# `USER_ENTITY` — putting the extras on the spec would close the cycle.
# Other framework verbs (none active for users today) and the state-axis
# / related-list dispatchers are spec-driven.
mount_entity(
    router,
    USER_ENTITY,
    handlers={
        "list": handle_list_users,
        "delete": handle_delete_user,
        # State axis (activation): action + body schema + response
        # projection all declared on `USER_ENTITY.state_axes[0]`.
        "activation": handle_set_user_activation,
        # Related-list subresource (providers); singleton-alias
        # `/users/me/providers` declared on the spec.
        "providers": handle_list_user_providers,
    },
    detail_extras=user_detail_extras,
    detail_extra_repos=(("provider_repo", ProviderRepository),),
)
