import logging
from typing import Literal

from fastapi import APIRouter

from src.api.common import BaseRouter
from src.api.common.resource_routes import (
    QueryParam,
    ResourceSpec,
    mount_create,
    mount_delete,
    mount_detail,
    mount_form,
    mount_list,
    mount_update,
)
from src.auth_config import current_active_user
from src.logic._authz import assert_owner_or_admin
from src.logic.posts.post_processing import (
    POST,
    handle_create_post,
    handle_delete_post,
    handle_get_post_detail,
    handle_get_post_edit_form,
    handle_get_post_form,
    handle_list_posts,
    handle_update_post,
)
from src.models import POST_KIND_NAMES, POST_KINDS
from src.repositories.dependencies import get_post_repository
from src.schemas.posts.post import post_create_adapter, post_update_adapter

posts_api_router = APIRouter(prefix="/posts")
router = BaseRouter(router=posts_api_router, default_tags=["posts"])
logger = logging.getLogger(__name__)


def _patch_response_body(post) -> dict:
    """Per-kind flat response body for `PATCH /posts/{id}`. The wire
    shape mirrors the POST/GET projection's flat fields so HTMX clients
    don't have to know about parent/detail. Per-kind detail relationship
    + fields come from `POST_KINDS` in `src/models/posts/post_kinds.py`."""
    spec = POST_KINDS[post.kind]
    detail = getattr(post, spec.detail_relationship)
    return {
        "id": str(post.id),
        "kind": post.kind,
        **{f: getattr(detail, f) for f in spec.detail_fields},
    }


POST_SPEC = ResourceSpec(
    collection="posts",
    id_param="post_id",
    repo_dep=get_post_repository,
    audit_resource=POST,
    read_user_dep=current_active_user,
    write_user_dep=current_active_user,
    write_authz=assert_owner_or_admin,
    create_adapter=post_create_adapter,
    update_adapter=post_update_adapter,
    read_to_dict=_patch_response_body,
    list_template="posts/list.html",
    detail_template="posts/detail.html",
    # After update, redirect to the detail page (not the form).
    update_redirect=lambda *, post_id: f"/posts/{post_id}",
    # Create has no `create_redirect` override — the mount's default
    # (HX-Redirect = Location = /posts/{id}) matches the previous shape.
)


# Route registration order matters: literal segments and longer paths must
# be registered before the more general `/{post_id}` so FastAPI doesn't
# match `form` as a UUID. The order below mirrors the path specificity.

# GET /posts — list page.
mount_list(router, POST_SPEC, handler=handle_list_posts)


# GET /posts/form?kind=<X> — `kind` query param picks the per-kind create
# template at request time. The handler returns `template_name` in the
# context dict; mount_form's three-source resolution picks it up.
mount_form(
    router,
    POST_SPEC,
    handler=handle_get_post_form,
    query_params=(
        QueryParam(
            "kind",
            Literal[*POST_KIND_NAMES],
            POST_KIND_NAMES[0],
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
mount_delete(router, POST_SPEC, handler=handle_delete_post)
