"""`CLINICIAN_ENTITY`: single declaration of the clinician directory resource.

Read by:
  - `src/domain/routes/clinicians.py` — derives `CLINICIAN_SPEC` for the
    mount helpers and reads the list filters from `.filters`.
  - `src/domain/specs/clinician_licensure.py` /
    `clinician_education.py` / `clinician_certification.py` — set
    ``parent=CLINICIAN_ENTITY`` so the mount layer's parent-chain
    machinery builds nested paths like
    ``/clinicians/{clinician_id}/licensures/{licensure_id}``.
  - `src/domain/specs/user.py` — the related-list subresource
    `RelatedListSubresource(child_spec=CLINICIAN_ENTITY.to_resource_spec(), ...)`
    on the user spec; closes the `api/common -> api/routes`
    inversion.
"""

from typing import Final

from src.domain.logic.clinician_affiliations.repository import (
    get_clinician_affiliation_repository,
)
from src.domain.logic.clinicians.repository import (
    ClinicianRepository,
    get_clinician_repository,
)
from src.domain.logic.clinicians.schema import (
    ClinicianCreate,
    ClinicianRead,
    ClinicianUpdate,
    ClinicianVerificationAuditSnapshot,
    ClinicianVerificationStateUpdate,
)
from src.domain.logic.favorites.repository import UserFavoriteRepository
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.posts.repository import get_post_repository
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import Clinician
from src.domain.models.enums import (
    CERTIFICATION_TYPES,
    CERTIFICATION_TYPES_LABELS,
    EDUCATION_TYPES,
    EDUCATION_TYPES_LABELS,
    LICENSE_TYPES,
    LICENSE_TYPES_LABELS,
    US_STATES,
)
from src.framework.audit.core import AuditAction
from src.framework.audit.repository import AuditRepository
from src.framework.dispatch.entity_spec import (
    AUTHENTICATED,
    OWNER_OR_ADMIN,
    EntitySpec,
    RelatedListSubresource,
    RouteSet,
    StateAxis,
    Templates,
)
from src.framework.dispatch.filters import ChoiceFilter
from src.framework.dispatch.mounts._spec import ResourceSpec
from src.framework.dispatch.redirects import Redirects

# Owner-scoped read projections over `/posts` (RESOURCE_GRAMMAR pattern
# #5): a clinician's openings and the referrals attributed to them. Both
# render `Post` rows, so the child spec points at the post repo; only
# `collection` / `id_param` / `repo_dep` are read by `mount_related_list`.
_clinician_openings_child = ResourceSpec(
    collection="openings", id_param="post_id", repo_dep=get_post_repository
)
_clinician_referrals_child = ResourceSpec(
    collection="referrals", id_param="post_id", repo_dep=get_post_repository
)

# The four canonical clinician sub-resources — `GET /clinicians/{id}/<sub>`
# pages. Hand-rolled inline child specs (matching the openings/referrals
# pattern above) avoid the import cycle that would result from pulling
# in `<SUB>_ENTITY.to_resource_spec()` here (each sub-entity spec
# imports `CLINICIAN_ENTITY`). The credential trio shares
# `get_clinician_repository` because credentials are loaded as relations
# on the parent clinician; affiliations have their own repo.
_clinician_affiliations_child = ResourceSpec(
    collection="clinician_affiliations",
    id_param="clinician_affiliation_id",
    repo_dep=get_clinician_affiliation_repository,
)
_clinician_licensures_child = ResourceSpec(
    collection="licensures",
    id_param="licensure_id",
    repo_dep=get_clinician_repository,
)
_clinician_educations_child = ResourceSpec(
    collection="educations",
    id_param="education_id",
    repo_dep=get_clinician_repository,
)
_clinician_certifications_child = ResourceSpec(
    collection="certifications",
    id_param="certification_id",
    repo_dep=get_clinician_repository,
)

# Post-update for the clinician itself: stay on the edit form so the
# user can keep iterating on the person-level fields.
_clinician_form_redirect = Redirects.to_edit_form("clinicians", "clinician_id")

# Post-mutation redirects for the four clinician sub-resources — after
# add/delete on any of them, send HTMX clients back to the sub-resource's
# own list page (the page the user is already on, post-#1336). Each
# child spec imports its own redirect from below.
_clinician_affiliations_list_redirect = Redirects.to_related_list(
    "clinicians", "clinician_id", "clinician_affiliations"
)
_clinician_licensures_list_redirect = Redirects.to_related_list(
    "clinicians", "clinician_id", "licensures"
)
_clinician_educations_list_redirect = Redirects.to_related_list(
    "clinicians", "clinician_id", "educations"
)
_clinician_certifications_list_redirect = Redirects.to_related_list(
    "clinicians", "clinician_id", "certifications"
)


# Post-create: drop the user on the homepage. NPPES verification now
# gates create (see `after_create_clinician_verification`), so a
# successful create means the clinician is already verified and ready
# — sending them into the edit form would push optional fields ahead of
# whatever they came here to do next.
def _clinician_create_redirect(**_: object) -> str:
    return "/"


CLINICIAN_ENTITY: Final[EntitySpec] = EntitySpec(
    name="clinician",
    url_collection="clinicians",
    id_param="clinician_id",
    model=Clinician,
    display_label_fn=lambda c: f"{c.first_name or ''} {c.last_name or ''}".strip()
    or "Clinician",
    repo_dep=get_clinician_repository,
    auth_deps=AUTHENTICATED,
    auth_policy=OWNER_OR_ADMIN,
    # No `read_policy`: the directory is reachable by every authenticated
    # viewer. Identifying fields are redacted per-row at render time when
    # the viewer lacks provider-network access AND isn't the owner — same
    # `redacted=` pattern posts use (see `posts/_shared/_facts_block.html`).
    create_adapter=ClinicianCreate,
    update_adapter=ClinicianUpdate,
    read_schema=ClinicianRead,
    routes=RouteSet(
        list=True,
        detail=True,
        create=True,
        update=True,
        delete=True,
        form_new=True,
        form_edit=True,
    ),
    # Declaring filters auto-mounts `/clinicians/search` (no separate
    # `routes.search` flag) and turns the list page's content area
    # into a two-column browse layout — sidebar form + results.
    filters=(
        # `?owner=me` scopes the list to clinicians the viewer owns,
        # bypassing the directory's verified-only gate so unverified
        # in-flight rows still surface to their creator. Rendered as
        # a single-toggle radio (Pico-style) above the license
        # filters; the viewer-id resolution happens in
        # `ClinicianRepository.list_clinicians` via the
        # `_requesting_user` field that `handle_list` stamps on the
        # repo.
        ChoiceFilter(
            name="owner",
            label="Owner",
            choices=(("me", "Mine only"),),
            multi=False,
            radio=True,
        ),
        ChoiceFilter(
            name="license_type",
            label="License type",
            choices=tuple((v, LICENSE_TYPES_LABELS[v]) for v in LICENSE_TYPES),
            multi=True,
        ),
        ChoiceFilter(
            name="issuing_state",
            label="Licensed in state",
            choices=tuple((s, s) for s in US_STATES),
            multi=True,
        ),
    ),
    create_redirect=_clinician_create_redirect,
    update_redirect=_clinician_form_redirect,
    # Opt into the HX-Request re-render-on-validation-failure path —
    # see `EntitySpec.form_error_render`. On a Pydantic 422 the
    # framework re-renders `clinicians/_form_new_fragment.html`
    # with `form_errors` / `form_values` injected.
    form_error_render=True,
    templates=Templates(
        list="clinicians/list.html",
        detail="clinicians/detail.html",
        form_new="clinicians/form_new.html",
        form_edit="clinicians/form_edit.html",
        search="clinicians/search.html",
    ),
    # Per-viewer detail extras live on the spec — see `EntitySpec`.
    detail_extras_path="src.domain.logic.clinicians.handlers.clinician_detail_extras",
    detail_extras_repos=(
        ("user_favorite_repo", UserFavoriteRepository),
        ("verification_repo", VerificationRepository),
    ),
    # The create/edit form's Org-picker dropdown is scoped per-viewer to
    # the user's owned Organizations. The framework invokes the extras
    # callable on both the create path (target=None) and the edit path
    # (target=<row>) — see `EntitySpec.form_extras_path`.
    form_extras_path="src.domain.logic.clinicians.handlers.clinician_form_extras",
    form_extras_repos=(("organization_repo", OrganizationRepository),),
    # Write-time check: a user may only attach a Clinician to an Org they own.
    # Create payloads don't carry `org_id`; on update, the FK-ownership
    # guard treats a missing FK as a no-op.
    payload_authz_path=(
        "src.domain.logic.clinicians.handlers._assert_clinician_payload_org_ownership"
    ),
    payload_authz_repos=(("organization_repo", OrganizationRepository),),
    # Run NPI verification immediately after a clinician row is persisted.
    # `verification_audit_repo` is the AuditRepository under a distinct
    # name because `audit_repo` is a reserved factory-handler kwarg and
    # cannot appear in `after_create_repos`.
    after_create_path=(
        "src.domain.logic.clinicians.handlers.after_create_clinician_verification"
    ),
    after_create_repos=(
        ("verification_repo", VerificationRepository),
        ("clinician_repo", ClinicianRepository),
        ("verification_audit_repo", AuditRepository),
    ),
    # Re-run NPI verification when a `PATCH /clinicians/{id}` changes `npi`
    # (canonical replacement for the retired
    # `POST /profile/clinician/{id}/identity` retry). Keyed on the value
    # changing, so non-NPI edits don't trigger a needless NPPES lookup.
    after_update_path=(
        "src.domain.logic.clinicians.handlers.after_update_clinician_verification"
    ),
    after_update_repos=(
        ("verification_repo", VerificationRepository),
        ("clinician_repo", ClinicianRepository),
        ("verification_audit_repo", AuditRepository),
    ),
    # Clinician templates render credential-type display labels and the
    # tuples behind the filter/select dropdowns. Tying them to the spec
    # (instead of Jinja globals) means a new credential-type tuple
    # doesn't need an edit in `core/templating.py`. The labels are
    # clinician-specific — posts and other entities don't read them —
    # so they belong here, not in shared template-global infrastructure.
    static_context={
        "LICENSE_TYPES": LICENSE_TYPES,
        "LICENSE_TYPES_LABELS": LICENSE_TYPES_LABELS,
        "EDUCATION_TYPES": EDUCATION_TYPES,
        "EDUCATION_TYPES_LABELS": EDUCATION_TYPES_LABELS,
        "CERTIFICATION_TYPES": CERTIFICATION_TYPES,
        "CERTIFICATION_TYPES_LABELS": CERTIFICATION_TYPES_LABELS,
    },
    state_axes=(
        # Admin override of `npi_match_status`. The inline NPI-submit
        # route auto-flips `failed`/`needs_review` to `mismatch` so the
        # row settles in a terminal state; this axis is how admin
        # closes the loop on edge cases (`matched` accepts, `mismatch`
        # rejects definitively, `pending` re-queues for the next
        # submit attempt).
        StateAxis(
            name="verification",
            body_schema=ClinicianVerificationStateUpdate,
            action=AuditAction.SET_CLINICIAN_VERIFICATION_STATE,
            handler_path=(
                "src.domain.logic.clinicians.handlers."
                "handle_set_clinician_verification_state"
            ),
            audit_snapshot=ClinicianVerificationAuditSnapshot,
            forbid_self=False,
        ),
    ),
    subresources=(
        RelatedListSubresource(
            child_spec=_clinician_openings_child,
            template="clinicians/openings_list.html",
            handler_path=(
                "src.domain.logic.posts.handlers.handle_list_clinician_openings"
            ),
        ),
        RelatedListSubresource(
            child_spec=_clinician_referrals_child,
            template="clinicians/referrals_list.html",
            handler_path=(
                "src.domain.logic.posts.handlers.handle_list_clinician_referrals"
            ),
        ),
        # Sub-resource list pages. Each is being converted to the
        # canonical resource pattern one at a time — when a sub-resource
        # opts into `list=True` on its own EntitySpec, the
        # `RelatedListSubresource` entry below is removed (no double-mount
        # of `GET /clinicians/{id}/<sub>`).
        #
        # Converted (mounted via the sub-resource's own EntitySpec):
        #   - clinician_licensure
        #
        # Pending conversion (still mounted here):
        RelatedListSubresource(
            child_spec=_clinician_affiliations_child,
            template="clinicians/clinician_affiliations_list.html",
            handler_path=(
                "src.domain.logic.clinicians.handlers."
                "handle_list_clinician_affiliations"
            ),
        ),
        RelatedListSubresource(
            child_spec=_clinician_educations_child,
            template="clinicians/educations_list.html",
            handler_path=(
                "src.domain.logic.clinicians.handlers."
                "handle_list_clinician_educations"
            ),
        ),
        RelatedListSubresource(
            child_spec=_clinician_certifications_child,
            template="clinicians/certifications_list.html",
            handler_path=(
                "src.domain.logic.clinicians.handlers."
                "handle_list_clinician_certifications"
            ),
        ),
    ),
)
