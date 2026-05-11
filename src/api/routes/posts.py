import logging

from fastapi import APIRouter

from src.api.common import BaseRouter
from src.api.common.resource_routes import mount_entity
from src.api.common.specs.post import POST_ENTITY
from src.logic.posts.post_processing import (
    handle_get_post_form,
    post_list_extras,
)

posts_api_router = APIRouter(prefix="/posts")
router = BaseRouter(router=posts_api_router, default_tags=["posts"])
logger = logging.getLogger(__name__)


# Every standard verb (list, detail, create, update, delete, form_edit)
# is factory-built. `list` auto-binds via `make_list_handler(POST_ENTITY)`
# with `post_list_extras` adding the registered `post_kinds` to the
# context so the list page can render its per-kind 'New X' links.
# `form_new` stays bespoke for the `?kind=` template dispatch.
mount_entity(
    router,
    POST_ENTITY,
    handlers={
        "form_new": handle_get_post_form,
    },
    list_extras=post_list_extras,
)
