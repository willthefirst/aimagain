"""`PROVIDER_ENTITY`: single declaration of the clinician directory resource.

`#642 PR 4` renamed the user-facing surface (URL family + entity name)
from "provider" to "clinician" while keeping the `Provider` Python class
and its model file intact — the rename is templates/URLs/audit-resource-
type only. The Python-side identity stays `PROVIDER_ENTITY`; the spec's
`name="clinician"` flows to `entity_url('clinician', ...)`, the
`/clinicians/...` URL family, and `audit.type="clinician"`. Enum names
(`CREATE_PROVIDER` etc.) are pinned via `audit_action_stem="provider"`
so historical audit rows keep their labels. See
`src/domain/models/providers/README.md` for the model-vs-UI vocabulary
gap.

Read by:
  - `src/domain/routes/providers.py` — derives `PROVIDER_SPEC` for the
    mount helpers and reads the list filters from `.filters`.
  - `src/logic/providers/provider_processing.py` — reads
    `PROVIDER_ENTITY.audit` for the `mutate(...)` resource binding.
  - `src/domain/specs/provider_licensure.py` /
    `provider_education.py` / `provider_certification.py` — set
    ``parent=PROVIDER_ENTITY`` so the mount layer's parent-chain
    machinery builds nested paths like
    ``/clinicians/{clinician_id}/licensures/{licensure_id}``.
  - `src/domain/specs/user.py` — the related-list subresource
    `RelatedListSubresource(child_spec=PROVIDER_ENTITY.to_resource_spec(), ...)`
    on the user spec; closes the `api/common -> api/routes`
    inversion.
"""

from typing import Final

from src.domain.logic.favorites.repository import UserFavoriteRepository
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.providers.repository import get_provider_repository
from src.domain.logic.providers.schema import (
    ProviderCreate,
    ProviderRead,
    ProviderUpdate,
)
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import Provider
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
_provider_form_redirect = Redirects.to_edit_form("clinicians", "clinician_id")


PROVIDER_ENTITY: Final[EntitySpec] = EntitySpec(
    name="clinician",
    url_collection="clinicians",
    id_param="clinician_id",
    # `audit_action_stem` pins the persisted enum names at `CREATE_PROVIDER`
    # / `UPDATE_PROVIDER` / `DELETE_PROVIDER` so existing audit rows keep
    # their historical labels — the rename is user-facing only. `audit.type`
    # still equals `spec.name` ("clinician") so *new* rows record the
    # post-rename resource type while the action enum reads as the old name.
    audit_action_stem="provider",
    model=Provider,
    # `owner_attr` defaults to "owner_id" — providers track their
    # owning user via Provider.owner_id.
    repo_dep=get_provider_repository,
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
    create_redirect=_provider_form_redirect,
    update_redirect=_provider_form_redirect,
    # Template paths are pinned explicitly because the directory cluster
    # is still `templates/providers/` (the Python model file lives at
    # `models/providers/provider.py` and the brief kept that filename
    # stable), but the spec's `url_collection` is now `"clinicians"` —
    # the default would resolve to `clinicians/<verb>.html` which doesn't
    # exist. Every opt-in route gets an explicit path here; conformance
    # tests (`test_spec_conformance.py::test_templates_default_by_convention_for_opted_in_verbs`)
    # tolerate the divergence.
    templates=Templates(
        list="providers/list.html",
        detail="providers/detail.html",
        form_new="providers/form_new.html",
        form_edit="providers/form_edit.html",
        search="providers/search.html",
    ),
    # Per-viewer detail extras live on the spec — see `EntitySpec`.
    detail_extras_path="src.domain.logic.providers.handlers.provider_detail_extras",
    detail_extras_repos=(
        ("user_favorite_repo", UserFavoriteRepository),
        ("verification_repo", VerificationRepository),
    ),
    # The create/edit form's Org-picker dropdown is scoped per-viewer to
    # the user's owned Organizations. The framework invokes the extras
    # callable on both the create path (target=None) and the edit path
    # (target=<row>) — see `EntitySpec.form_extras_path`.
    form_extras_path="src.domain.logic.providers.handlers.provider_form_extras",
    form_extras_repos=(("organization_repo", OrganizationRepository),),
    # Write-time check: a user may only attach a Provider to an Org they own.
    payload_authz_path=(
        "src.domain.logic.providers.handlers._assert_provider_payload_org_ownership"
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
