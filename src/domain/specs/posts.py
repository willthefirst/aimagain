"""`POST_ENTITY` — the single whole-supertype URL face for ``/posts``.

`Post` is the codebase's only polymorphic entity: the supertype owns
the cross-kind invariants (``owner_id``, ``created_at``, audit shape)
while three detail tables (``referral_detail``, ``opening_detail``,
``intake_detail``) carry the per-kind fields. One URL family lists
every kind; the create/edit forms dispatch by ``?kind=X`` on the URL
and the framework's discriminated-union adapter handles dispatch on
POST/PATCH bodies. List/search expose a `kind` filter for narrowing
to one kind without leaving ``/posts``.

See the `discriminator` / `discriminator_value` docstring in
[`framework/dispatch/entity_spec.py`](../../framework/dispatch/entity_spec.py)
for the full polymorphic-face contract.
"""

from typing import Final

from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.posts.repository import get_post_repository
from src.domain.logic.posts.schema import (
    post_audit_snapshot,
    post_create_adapter,
    post_read_adapter,
    post_update_adapter,
)
from src.domain.logic.programs.repository import ProgramRepository
from src.domain.models import POST_KINDS, Post
from src.domain.models.enums import (
    CLIENT_AGE_GROUP_LABELS,
    CLIENT_AGE_GROUPS,
    INSURANCE_CARRIER_LABELS,
    INSURANCE_CARRIERS,
    LANGUAGE_LABELS,
    LANGUAGES,
    TREATMENT_MODALITIES,
    TREATMENT_MODALITY_LABELS,
    TREATMENT_SETTINGS,
    TREATMENT_SETTINGS_LABELS,
    US_STATES,
)
from src.framework.audit.core import make_audited_resource
from src.framework.dispatch.entity_spec import (
    AUTHENTICATED,
    OWNER_OR_ADMIN,
    EntitySpec,
    RouteSet,
    Templates,
)
from src.framework.dispatch.filters import ChoiceFilter, FlagFilter, TextFilter
from src.framework.dispatch.redirects import Redirects

POST_AUDITED_RESOURCE: Final = make_audited_resource(
    "post",
    post_audit_snapshot,
)


POST_ENTITY: Final[EntitySpec] = EntitySpec(
    name="post",
    url_collection="posts",
    id_param="post_id",
    model=Post,
    repo_dep=get_post_repository,
    auth_deps=AUTHENTICATED,
    auth_policy=OWNER_OR_ADMIN,
    audit=POST_AUDITED_RESOURCE,
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
    # Whole-supertype face: `kind` filter exposes the full registry of
    # kinds so list/search can narrow to one kind without leaving
    # ``/posts``. Each kind's display label comes from `POST_KINDS[k].list_label`.
    filters=(
        ChoiceFilter(
            name="kind",
            label="Type",
            choices=tuple((k, POST_KINDS[k].list_label) for k in POST_KINDS.names),
            multi=True,
        ),
        TextFilter(name="q", label="Description", placeholder="Search descriptions…"),
        TextFilter(
            name="posted_by", label="Posted by", placeholder="Username contains…"
        ),
        ChoiceFilter(
            name="state",
            label="State",
            choices=tuple((s, s) for s in US_STATES),
            multi=True,
        ),
        TextFilter(name="city", label="City", placeholder="City contains…"),
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
        TextFilter(
            name="geography",
            label="Location",
            placeholder="City, state, or ZIP…",
        ),
        FlagFilter(
            name="include_telehealth",
            label="Telehealth",
            label_checked="Include telehealth in CA",
        ),
        ChoiceFilter(
            name="level_of_care",
            label="Level of care",
            choices=tuple(
                (v, TREATMENT_SETTINGS_LABELS[v]) for v in TREATMENT_SETTINGS
            ),
            multi=True,
        ),
        ChoiceFilter(
            name="modality",
            label="Modality",
            choices=tuple(
                (v, TREATMENT_MODALITY_LABELS[v]) for v in TREATMENT_MODALITIES
            ),
            multi=True,
        ),
        ChoiceFilter(
            name="insurance",
            label="Insurance",
            choices=tuple((v, INSURANCE_CARRIER_LABELS[v]) for v in INSURANCE_CARRIERS),
            multi=True,
        ),
    ),
    templates=Templates(
        list="posts/list.html",
        detail="posts/detail.html",
        search="posts/search.html",
        form_new="posts/form_new.html",
        form_edit="posts/form_edit.html",
    ),
    update_redirect=Redirects.to_detail("posts", "post_id"),
    # Two authority paths on create (see `_assert_post_payload_authz`):
    # the **self** path (own the per-kind FK row + hold the matching
    # claim) or the **org-rep** path (be a verified rep of the org the
    # listing's `clinician_affiliation_id` points at). The org lookup for
    # the rep path needs `organization_repo`; the self path needs the
    # clinician/program repos for the FK-ownership check.
    payload_authz_path="src.domain.logic.posts.handlers._assert_post_payload_authz",
    payload_authz_repos=(
        ("clinician_repo", ClinicianRepository),
        ("program_repo", ProgramRepository),
        ("organization_repo", OrganizationRepository),
    ),
    discriminator=POST_KINDS,
    # Whole-supertype: no `discriminator_value` or `discriminator_values`.
    # List takes any kind; `?kind=` query param picks the create-form
    # template; the discriminated-union adapter dispatches POST/PATCH.
    form_error_render=True,
)
