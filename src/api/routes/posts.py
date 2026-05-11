import logging

from fastapi import APIRouter

from src.api.common import BaseRouter
from src.api.common.resource_routes import mount_entity
from src.api.common.specs.post import POST_ENTITY
from src.logic._generic import (
    make_create_handler,
    make_delete_handler,
    make_detail_handler,
    make_edit_form_handler,
    make_update_handler,
)
from src.logic.posts.post_processing import (
    handle_get_post_form,
    handle_list_posts,
)

posts_api_router = APIRouter(prefix="/posts")
router = BaseRouter(router=posts_api_router, default_tags=["posts"])
logger = logging.getLogger(__name__)


def _named(handler, name):
    """Give a factory-built handler a stable module attribute so
    contract-test patches at `src.api.routes.posts._handle_<verb>_post`
    flow through the mount layer's `_resolve_handler`."""
    handler.__name__ = name
    handler.__qualname__ = name
    handler.__module__ = __name__
    return handler


_handle_create_post = _named(make_create_handler(POST_ENTITY), "_handle_create_post")
_handle_update_post = _named(make_update_handler(POST_ENTITY), "_handle_update_post")
_handle_delete_post = _named(make_delete_handler(POST_ENTITY), "_handle_delete_post")
_handle_get_post_detail = _named(
    make_detail_handler(POST_ENTITY), "_handle_get_post_detail"
)
_handle_get_post_edit_form = _named(
    make_edit_form_handler(POST_ENTITY), "_handle_get_post_edit_form"
)


mount_entity(
    router,
    POST_ENTITY,
    handlers={
        "list": handle_list_posts,
        # Detail + edit form + CRUD verbs all framework-generated. The
        # create form stays bespoke (its `?kind=` Query default + template
        # lookup need the handler-context approach).
        "detail": _handle_get_post_detail,
        "create": _handle_create_post,
        "update": _handle_update_post,
        "delete": _handle_delete_post,
        "form_new": handle_get_post_form,
        "form_edit": _handle_get_post_edit_form,
    },
)
