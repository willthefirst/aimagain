"""Shared builder for the three kind-locked post faces.

Posts is the codebase's only polymorphic entity: the `Post` model owns
the cross-kind invariants (``author_id``, ``created_at``, audit shape)
while three detail tables (``referral_details``, ``opening_details``,
``intake_details``) carry the per-kind fields. Each kind has its own
URL family — ``/referrals``, ``/openings``, ``/intakes`` — declared
via `EntitySpec(discriminator_value=...)`. The supertype `Post` is no
longer exposed at `/posts`; consumers walk the three faces.

`_post_face(...)` builds one face. All three faces share the same:

  - audit `AuditedResource` (built once in this module so the
    persisted ``audit_log.resource_type`` stays ``"post"`` across all
    three families — no migration, audit-log readers don't see a
    rename),
  - `discriminator=POST_KINDS` registry (the framework's
    `handle_create` / `handle_update` reads through it to find each
    kind's `detail_model` / `detail_relationship`),
  - filter set (the six non-kind filters: q, posted_by, state, city,
    age_group, language),
  - payload-authz path (the per-kind FK-ownership dispatcher),
  - read schema, list ordering, repo dep, auth deps.

Each face overrides only:

  - `name` (``referral`` / ``opening`` / ``intake``),
  - `url_collection` (``referrals`` / ``openings`` / ``intakes``),
  - `discriminator_value` (the bound kind),
  - `create_adapter` / `update_adapter` (the per-kind schema, not the
    discriminated union),
  - `update_redirect` (kind-specific detail URL).
"""

from typing import Final

from src.domain.logic.posts.repository import get_post_repository
from src.domain.logic.posts.schema import (
    post_audit_snapshot,
    post_read_adapter,
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
from src.framework.audit.core import make_audited_resource
from src.framework.dispatch.entity_spec import (
    AUTHENTICATED,
    OWNER_OR_ADMIN,
    EntitySpec,
    Redirects,
    RouteSet,
)
from src.framework.dispatch.filters import ChoiceFilter, TextFilter

# Single `AuditedResource` shared across all three faces — keeps the
# persisted ``audit_log.resource_type`` column at ``"post"`` so existing
# audit rows survive the URL split without a backfill migration. The
# three face specs all carry `audit=POST_AUDITED_RESOURCE`; a pin test
# in `test_post_faces.py` asserts the identity to catch any drift.
POST_AUDITED_RESOURCE: Final = make_audited_resource(
    "post",
    post_audit_snapshot,
)


# The six filters that survive the kind split — `kind` is dropped
# because each face's list page is bound to one kind by the framework
# (handle_list forces `filter_values["kind"] = discriminator_value`).
_POST_FILTERS: Final = (
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
)


def _post_face(
    *,
    name: str,
    url_collection: str,
    kind: str,
    create_adapter: type,
    update_adapter: type,
) -> EntitySpec:
    """Construct one kind-locked face of the polymorphic post entity.

    ``kind`` must match one of `POST_KINDS.names` — the framework
    validates this at spec construction time via the
    `discriminator_value must be in registry` check.
    """
    return EntitySpec(
        name=name,
        url_collection=url_collection,
        id_param="post_id",
        model=Post,
        repo_dep=get_post_repository,
        auth_deps=AUTHENTICATED,
        auth_policy=OWNER_OR_ADMIN,
        audit=POST_AUDITED_RESOURCE,
        create_adapter=create_adapter,
        update_adapter=update_adapter,
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
        filters=_POST_FILTERS,
        update_redirect=Redirects.to_detail(url_collection, "post_id"),
        # Same per-kind FK-ownership check as the old `POST_ENTITY` — the
        # dispatcher reads `payload.kind` and validates the kind-specific
        # FK fields (opening's `provider_id`, intake's `program_id`)
        # against the requesting user's ownership.
        payload_authz_path=(
            "src.domain.logic.posts.handlers._assert_post_payload_target_ownership"
        ),
        payload_authz_repos=(
            ("provider_repo", ProviderRepository),
            ("program_repo", ProgramRepository),
        ),
        discriminator=POST_KINDS,
        discriminator_value=kind,
    )
