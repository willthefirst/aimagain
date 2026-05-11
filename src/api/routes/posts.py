import logging

from fastapi import APIRouter

from src.api.common import BaseRouter
from src.api.common.resource_routes import mount_entity
from src.api.common.specs.post import POST_ENTITY
from src.logic.posts.post_processing import (
    handle_get_post_form,
    handle_list_posts,
)

posts_api_router = APIRouter(prefix="/posts")
router = BaseRouter(router=posts_api_router, default_tags=["posts"])
logger = logging.getLogger(__name__)


# Every standard CRUD verb (detail, create, update, delete, form_edit) is
# factory-built — `mount_entity` reads `POST_ENTITY.routes`, calls the
# matching `make_<verb>_handler(POST_ENTITY)`, and stitches the result
# onto this module so contract-test patches at
# `src.api.routes.posts._handle_<verb>_post` resolve through
# `_resolve_handler`. The bespoke handlers stay in `handlers={}` — list
# (filtering shape) and form_new (`?kind=` template dispatch via the
# polymorphic discriminator).
mount_entity(
    router,
    POST_ENTITY,
    handlers={
        "list": handle_list_posts,
        "form_new": handle_get_post_form,
    },
    module=__name__,
)
