"""`POST_ENTITY`: single declaration of the post resource.

Posts is the codebase's only polymorphic entity — each post has a
``kind`` discriminator (`client_referral`, `provider_availability`,
…) whose per-variant detail row lives in a separate table. The
discriminator binding is declared on the spec via
``discriminator=POST_KINDS``; layer files that need the registry's
*contents* (logic / schema / repo dispatch ladders) keep their
direct imports — only the route file's ``Literal[*kind names]`` for
the form ``?kind=`` query param reads through the spec.

Read by:
  - `src/api/routes/posts.py` — derives `POST_SPEC` for the mount
    helpers and builds the form's kind Literal from
    ``POST_ENTITY.discriminator.names``.
  - `src/logic/posts/post_processing.py` — reads `POST_ENTITY.audit`
    for the `mutate(...)` resource binding (via a thin `POST`
    re-export for handler ergonomics).
"""

from typing import Final

from src.api.common.entity_spec import EntitySpec, RouteSet
from src.auth_config import current_active_user
from src.logic._authz import assert_owner_or_admin, is_owner_or_admin
from src.models import POST_KINDS, Post
from src.repositories.dependencies import get_post_repository
from src.schemas.posts.post import (
    post_audit_snapshot,
    post_create_adapter,
    post_update_adapter,
)


def _post_read_to_dict(post: Post) -> dict:
    """Per-kind flat response body for `PATCH /posts/{id}`.

    The wire shape mirrors the POST/GET projection's flat fields so
    HTMX clients don't have to know about parent/detail. Per-kind
    detail relationship + fields come from `POST_KINDS`; reading
    them here rather than in the route file keeps the projection
    co-located with the spec it serves.
    """
    spec = POST_KINDS[post.kind]
    detail = getattr(post, spec.detail_relationship)
    return {
        "id": str(post.id),
        "kind": post.kind,
        **{f: getattr(detail, f) for f in spec.detail_fields},
    }


def _post_update_redirect(*, post_id, **_) -> str:
    return f"/posts/{post_id}"


POST_ENTITY: Final[EntitySpec] = EntitySpec(
    name="post",
    url_collection="posts",
    id_param="post_id",
    model=Post,
    # `owner_attr` defaults to "owner_id" — posts track their owner via Post.owner_id.
    repo_dep=get_post_repository,
    read_user_dep=current_active_user,
    write_user_dep=current_active_user,
    write_authz=assert_owner_or_admin,
    can_write=is_owner_or_admin,
    audit_snapshot=post_audit_snapshot,
    create_adapter=post_create_adapter,
    update_adapter=post_update_adapter,
    read_to_dict=_post_read_to_dict,
    routes=RouteSet(
        list=True,
        detail=True,
        create=True,
        update=True,
        delete=True,
        form_new=True,
        form_edit=True,
    ),
    update_redirect=_post_update_redirect,
    discriminator=POST_KINDS,
)
