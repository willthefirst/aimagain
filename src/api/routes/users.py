import logging

from fastapi import APIRouter

from src.api.common import BaseRouter
from src.api.common.resource_routes import mount_entity
from src.api.common.specs.user import USER_ENTITY
from src.logic.users.user_processing import (
    handle_delete_user,
    handle_list_users,
    user_detail_extras,
)
from src.repositories.providers.provider_repository import ProviderRepository

users_api_router = APIRouter(prefix="/users")
router = BaseRouter(router=users_api_router, default_tags=["users"])
logger = logging.getLogger(__name__)


# `handle_delete_user` and `handle_list_users` are bespoke (self-guard
# on delete; per-viewer admin flag on list); the detail handler is
# factory-built but takes a per-viewer `user_detail_extras` callable
# (loads owned providers + projects `target_user` via
# `USER_ENTITY.private_fields`). The extras live at the call site
# rather than on the spec because `user_detail_extras` itself imports
# `USER_ENTITY` — putting the extras on the spec would close the cycle.
# The state-axis (`activation`) and related-list subresource
# (`providers`) handlers are bound via `handler_path` strings on the
# spec — `mount_entity` resolves them at mount time without forcing
# `specs/user.py` to import `src.logic`.
mount_entity(
    router,
    USER_ENTITY,
    handlers={
        "list": handle_list_users,
        "delete": handle_delete_user,
    },
    detail_extras=user_detail_extras,
    detail_extra_repos=(("provider_repo", ProviderRepository),),
)
