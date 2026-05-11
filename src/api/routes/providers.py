import logging

from fastapi import APIRouter

from src.api.common import BaseRouter
from src.api.common.resource_routes import mount_entity
from src.api.common.specs.provider import PROVIDER_ENTITY
from src.api.common.specs.provider_certification import CERTIFICATION_ENTITY
from src.api.common.specs.provider_education import EDUCATION_ENTITY
from src.api.common.specs.provider_licensure import LICENSURE_ENTITY
from src.logic.providers.provider_processing import (
    handle_create_provider,
    handle_get_provider_form,
    handle_list_providers,
    provider_detail_extras,
)
from src.repositories.favorites.user_favorite_repository import UserFavoriteRepository

providers_api_router = APIRouter(prefix="/providers")
router = BaseRouter(router=providers_api_router, default_tags=["providers"])
logger = logging.getLogger(__name__)


# Bespoke handlers (list, create — inline credentials append, form_new)
# stay explicit; the detail handler takes a per-viewer `is_favorited`
# extras callable. Update / delete / form_edit are framework-built by
# `mount_entity` via `make_<verb>_handler(PROVIDER_ENTITY)` and stitched
# onto this module (auto-detected from the caller frame) for
# contract-test patches at
# `src.api.routes.providers._handle_<verb>_provider`. Owned credential
# subentities (licensure, education, certification) auto-bind their own
# create/update/delete factories — same path through `mount_entity`'s
# owned-subentity branch.
mount_entity(
    router,
    PROVIDER_ENTITY,
    handlers={
        "list": handle_list_providers,
        "create": handle_create_provider,
        "form_new": handle_get_provider_form,
    },
    detail_extras=provider_detail_extras,
    detail_extra_repos=(("user_favorite_repo", UserFavoriteRepository),),
    owned_subentities=(LICENSURE_ENTITY, EDUCATION_ENTITY, CERTIFICATION_ENTITY),
)
