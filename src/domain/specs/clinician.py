"""`CLINICIAN_ENTITY`: single declaration of the clinician directory resource.

`#642 PR 4` renamed the user-facing surface (URL family + entity name)
from "provider" to "clinician". Enum names (`CREATE_PROVIDER` etc.) are
pinned via `audit_action_stem="provider"` so historical audit rows keep
their labels. See `src/domain/models/providers/README.md` for the
model-vs-UI vocabulary gap.

Read by:
  - `src/domain/routes/clinicians.py` — derives `CLINICIAN_SPEC` for the
    mount helpers and reads the list filters from `.filters`.
  - `src/domain/specs/provider_licensure.py` /
    `provider_education.py` / `provider_certification.py` — set
    ``parent=CLINICIAN_ENTITY`` so the mount layer's parent-chain
    machinery builds nested paths like
    ``/clinicians/{clinician_id}/licensures/{licensure_id}``.
  - `src/domain/specs/user.py` — the related-list subresource
    `RelatedListSubresource(child_spec=CLINICIAN_ENTITY.to_resource_spec(), ...)`
    on the user spec; closes the `api/common -> api/routes`
    inversion.
"""

from typing import Final

from src.domain.logic.clinicians.repository import get_clinician_repository
from src.domain.logic.clinicians.schema import (
    ProviderCreate,
    ProviderRead,
    ProviderUpdate,
)
from src.domain.logic.favorites.repository import UserFavoriteRepository
from src.domain.logic.organizations.repository import OrganizationRepository
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
from src.framework.dispatch.entity_spec import (
    AUTHENTICATED,
    OWNER_OR_ADMIN,
    EntitySpec,
    Redirects,
    RouteSet,
    Templates,
)
from src.framework.dispatch.filters import ChoiceFilter

# After create or update, redirect to the edit form so the user can
# keep editing the parent + its credentials. The same callable is reused
# by the three credential subentities (their parent is this clinician
# directory entry).
_clinician_form_redirect = Redirects.to_edit_form("clinicians", "clinician_id")

# Backward-compat alias for credential specs that import the old name.
_provider_form_redirect = _clinician_form_redirect


CLINICIAN_ENTITY: Final[EntitySpec] = EntitySpec(
    name="clinician",
    url_collection="clinicians",
    id_param="clinician_id",
    # `audit_action_stem` pins the persisted enum names at `CREATE_PROVIDER`
    # / `UPDATE_PROVIDER` / `DELETE_PROVIDER` so existing audit rows keep
    # their historical labels — the rename is user-facing only. `audit.type`
    # still equals `spec.name` ("clinician") so *new* rows record the
    # post-rename resource type while the action enum reads as the old name.
    audit_action_stem="provider",
    model=Clinician,
    repo_dep=get_clinician_repository,
    auth_deps=AUTHENTICATED,
    auth_policy=OWNER_OR_ADMIN,
    create_adapter=ProviderCreate,
    update_adapter=ProviderUpdate,
    read_schema=ProviderRead,
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
    # Filters render on the dedicated `/clinicians/search` page; the
    # list-page toolbar carries only the "Filter · N" link and the
    # Create button.
    filters=(
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
    create_redirect=_clinician_form_redirect,
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
    payload_authz_path=(
        "src.domain.logic.clinicians.handlers._assert_clinician_payload_org_ownership"
    ),
    payload_authz_repos=(("organization_repo", OrganizationRepository),),
    # Provider templates render credential-type display labels and the
    # tuples behind the filter/select dropdowns. Tying them to the spec
    # (instead of Jinja globals) means a new credential-type tuple
    # doesn't need an edit in `core/templating.py`. The labels are
    # provider-specific — posts and other entities don't read them —
    # so they belong here, not in shared template-global infrastructure.
    static_context={
        "LICENSE_TYPES": LICENSE_TYPES,
        "LICENSE_TYPES_LABELS": LICENSE_TYPES_LABELS,
        "EDUCATION_TYPES": EDUCATION_TYPES,
        "EDUCATION_TYPES_LABELS": EDUCATION_TYPES_LABELS,
        "CERTIFICATION_TYPES": CERTIFICATION_TYPES,
        "CERTIFICATION_TYPES_LABELS": CERTIFICATION_TYPES_LABELS,
    },
)
