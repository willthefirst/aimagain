import logging

from fastapi import APIRouter

from src.api.common import BaseRouter
from src.api.common.resource_routes import mount_entity
from src.api.common.specs.user import USER_ENTITY
from src.logic._generic import make_detail_handler
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


def _named(handler, name):
    handler.__name__ = name
    handler.__qualname__ = name
    handler.__module__ = __name__
    return handler


_handle_get_user_detail = _named(
    make_detail_handler(
        USER_ENTITY,
        extras=user_detail_extras,
        extra_repos=(("provider_repo", ProviderRepository),),
    ),
    "_handle_get_user_detail",
)


# `handle_delete_user` is bespoke (self-guard); other handlers (detail,
# list, activation, providers) come from the framework or the providers
# cluster. `mount_entity` reads `USER_ENTITY`'s routes / state_axes /
# subresources / singleton_alias and dispatches to the appropriate
# `mount_*` helpers.
mount_entity(
    router,
    USER_ENTITY,
    handlers={
        "list": handle_list_users,
        # Detail is framework-built; `user_detail_extras` loads owned
        # providers, computes viewer flags, and projects `target_user`
        # via `USER_ENTITY.private_fields` for the defense-in-depth
        # private-field omission.
        "detail": _handle_get_user_detail,
        "delete": handle_delete_user,
        # State axis (activation): action + body schema + response
        # projection all declared on `USER_ENTITY.state_axes[0]`.
        "activation": handle_set_user_activation,
        # Related-list subresource (providers); singleton-alias
        # `/users/me/providers` declared on the spec.
        "providers": handle_list_user_providers,
    },
)
