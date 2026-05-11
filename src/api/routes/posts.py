import logging
from typing import Literal

from fastapi import APIRouter

from src.api.common import BaseRouter
from src.api.common.resource_routes import (
    QueryParam,
    mount_create,
    mount_delete,
    mount_detail,
    mount_form,
    mount_list,
    mount_update,
)
from src.api.common.specs.post import POST_ENTITY
from src.logic._generic import make_delete_handler
from src.logic.posts.post_processing import (
    handle_create_post,
    handle_get_post_detail,
    handle_get_post_edit_form,
    handle_get_post_form,
    handle_list_posts,
    handle_update_post,
)

posts_api_router = APIRouter(prefix="/posts")
router = BaseRouter(router=posts_api_router, default_tags=["posts"])
logger = logging.getLogger(__name__)


# `POST_ENTITY` is the single declaration of identity (audit binding,
# adapters, redirects, route flags, templates, polymorphism). The mount
# helpers still consume `ResourceSpec`, so we bridge via
# `to_resource_spec()`.
POST_SPEC = POST_ENTITY.to_resource_spec()


# Route registration order matters: literal segments and longer paths must
# be registered before the more general `/{post_id}` so FastAPI doesn't
# match `form` as a UUID. The order below mirrors the path specificity.

# GET /posts — list page.
mount_list(router, POST_SPEC, handler=handle_list_posts)


# GET /posts/form?kind=<X> — `kind` query param picks the per-kind create
# template at request time. The handler returns `template_name` in the
# context dict; mount_form's three-source resolution picks it up. The
# kind Literal is built from the spec's discriminator binding so the
# spec is the source of truth for which kinds are valid.
_post_kind_names = POST_ENTITY.discriminator.names
mount_form(
    router,
    POST_SPEC,
    handler=handle_get_post_form,
    query_params=(
        QueryParam(
            "kind",
            Literal[*_post_kind_names],
            _post_kind_names[0],
            description="Which post kind's create form to render.",
        ),
    ),
)


# GET /posts/{post_id}/form — handler returns `template_name` in context
# so mount_form picks the right kind-specific edit template at request time.
mount_form(
    router,
    POST_SPEC,
    handler=handle_get_post_edit_form,
    on_existing=True,
)


# GET /posts/{post_id} — detail page. Registered after /form and /{id}/form
# so literal segments take precedence.
mount_detail(router, POST_SPEC, handler=handle_get_post_detail)


# Mutations — methods differ from the GETs above so order is independent.
mount_create(router, POST_SPEC, handler=handle_create_post)
mount_update(router, POST_SPEC, handler=handle_update_post)
# Named module-level attribute so test monkeypatching (contract tests)
# can target `src.api.routes.posts._handle_delete_post` and the mount
# layer's `_resolve_handler` picks up the patched version.
_handle_delete_post = make_delete_handler(POST_ENTITY)
_handle_delete_post.__module__ = __name__
mount_delete(router, POST_SPEC, handler=_handle_delete_post)
