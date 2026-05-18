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
  - `src/domain/routes/posts.py` — derives `POST_SPEC` for the mount
    helpers and builds the form's kind Literal from
    ``POST_ENTITY.discriminator.names``.
"""

from typing import Final, Literal

from src.domain.logic.posts.schema import (
    post_audit_snapshot,
    post_create_adapter,
    post_read_adapter,
    post_update_adapter,
)
from src.domain.logic.programs.repository import ProgramRepository
from src.domain.logic.providers.repository import ProviderRepository
from src.domain.models import POST_KINDS, Post
from src.domain.models.enums import (
    CLIENT_AGE_GROUP_LABELS,
    CLIENT_AGE_GROUPS,
    LANGUAGE_LABELS,
    LANGUAGES,
    US_STATES,
)
from src.framework.dispatch.entity_spec import (
    AUTHENTICATED,
    OWNER_OR_ADMIN,
    EntitySpec,
    Redirects,
    RouteSet,
)
from src.framework.dispatch.filters import ChoiceFilter, TextFilter
from src.framework.persistence.dependencies import get_post_repository

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
        search=True,
    ),
    # Filter form above `/posts` — one control per table column the
    # user might want to narrow on. Order roughly matches the column
    # order so the form reads top-to-bottom like the table.
    #
    # Polymorphic axes (state, city, age_group, language) OR across
    # both detail tables in `PostRepository.list_posts`; the repo
    # owns the SQL because the column set is post-specific.
    # Two columns are deliberately *not* filterable yet:
    #   * `created_at` — needs a `DateRangeFilter` type (not yet built).
    #   * insurance posture — CR stores `network_preference` directly
    #     in the unified vocab; PA derives posture at view time from
    #     `Provider.in_network_carriers` (truthy) +
    #     `accepts_out_of_network` / `sliding_scale`. Adding the filter
    #     needs either a per-kind mapping in the repo or normalizing
    #     PA's storage — deferred.
    filters=(
        ChoiceFilter(
            name="kind",
            label="Type",
            choices=(
                ("client_referral", "Seeking"),
                ("provider_availability", "Providing"),
                ("program_availability", "Program offering"),
            ),
            radio=True,
            value_type=Literal[*POST_KINDS.names],  # type: ignore[valid-type]
        ),
        TextFilter(
            name="q",
            label="Description",
            placeholder="Search descriptions…",
        ),
        TextFilter(
            name="posted_by",
            label="Posted by",
            placeholder="Username contains…",
        ),
        ChoiceFilter(
            name="state",
            label="State",
            choices=tuple((s, s) for s in US_STATES),
            multi=True,
        ),
        TextFilter(
            name="city",
            label="City",
            placeholder="City contains…",
        ),
        ChoiceFilter(
            name="age_group",
            label="Age groups",
            choices=tuple((v, CLIENT_AGE_GROUP_LABELS[v]) for v in CLIENT_AGE_GROUPS),
            multi=True,
        ),
        ChoiceFilter(
            name="language",
            label="Languages",
            choices=tuple((v, LANGUAGE_LABELS[v]) for v in LANGUAGES),
            multi=True,
        ),
    ),
    update_redirect=Redirects.to_detail("posts", "post_id"),
    # Wire-side authz on per-kind FK fields. Dispatches on ``payload.kind``:
    # PA's ``provider_id`` and Program-availability's ``program_id`` must
    # point at rows the requesting user owns (superusers bypass). See
    # ``src/domain/logic/posts/handlers.py`` for the dispatcher.
    payload_authz_path=(
        "src.domain.logic.posts.handlers._assert_post_payload_target_ownership"
    ),
    payload_authz_repos=(
        ("provider_repo", ProviderRepository),
        ("program_repo", ProgramRepository),
    ),
    discriminator=POST_KINDS,
    # The list page renders per-kind "New X" links from this tuple —
    # consumed by `src/domain/templates/posts/list.html`. Computed once at
    # spec-construction time; the registry is immutable after import.
    static_context={"post_kinds": list(POST_KINDS.values())},
)
