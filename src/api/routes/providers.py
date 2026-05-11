import logging

from fastapi import APIRouter

from src.api.common import BaseRouter
from src.api.common.resource_routes import mount_entity
from src.api.common.specs.provider import PROVIDER_ENTITY
from src.api.common.specs.provider_certification import CERTIFICATION_ENTITY
from src.api.common.specs.provider_education import EDUCATION_ENTITY
from src.api.common.specs.provider_licensure import LICENSURE_ENTITY
from src.logic.providers.provider_processing import (
    handle_get_provider_form,
    provider_detail_extras,
)
from src.repositories.favorites.user_favorite_repository import UserFavoriteRepository

providers_api_router = APIRouter(prefix="/providers")
router = BaseRouter(router=providers_api_router, default_tags=["providers"])
logger = logging.getLogger(__name__)


# Only `form_new` stays bespoke (the create-form template needs the
# Pydantic class as a Jinja field-resolver). Every other verb auto-binds:
# `create` reads `PROVIDER_ENTITY.children` to append inline credential
# rows; `list` echoes filter selections; detail/update/delete/form_edit
# go through the standard factories. Owned credential subentities
# (licensure, education, certification) self-register on
# `PROVIDER_ENTITY.children` and pick up the same auto-bind for their
# create / update / delete factories.
mount_entity(
    router,
    PROVIDER_ENTITY,
    handlers={
        "form_new": handle_get_provider_form,
    },
    detail_extras=provider_detail_extras,
    detail_extra_repos=(("user_favorite_repo", UserFavoriteRepository),),
    owned_subentities=(LICENSURE_ENTITY, EDUCATION_ENTITY, CERTIFICATION_ENTITY),
)
