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

from src.domain.posts.schema import (
    post_audit_snapshot,
    post_create_adapter,
    post_read_adapter,
    post_update_adapter,
)
from src.framework.dependencies import get_post_repository
from src.framework.entity_spec import (
    AUTHENTICATED,
    OWNER_OR_ADMIN,
    EntitySpec,
    Redirects,
    RouteSet,
)
from src.models import POST_KINDS, Post

POST_ENTITY: Final[EntitySpec] = EntitySpec(
    name="post",
    url_collection="posts",
    id_param="post_id",
    model=Post,
    # `owner_attr` defaults to "owner_id" — posts track their owner via Post.owner_id.
    repo_dep=get_post_repository,
    auth_deps=AUTHENTICATED,
    auth_policy=OWNER_OR_ADMIN,
    audit_snapshot=post_audit_snapshot,
    create_adapter=post_create_adapter,
    update_adapter=post_update_adapter,
    read_schema=post_read_adapter,
    list_order_by=Post.created_at.desc(),
    routes=RouteSet(
        list=True,
        detail=True,
        create=True,
        update=True,
        delete=True,
        form_new=True,
        form_edit=True,
    ),
    update_redirect=Redirects.to_detail("posts", "post_id"),
    discriminator=POST_KINDS,
    # The list page renders per-kind "New X" links from this tuple —
    # consumed by `src/templates/posts/list.html`. Computed once at
    # spec-construction time; the registry is immutable after import.
    static_context={"post_kinds": list(POST_KINDS.values())},
)
