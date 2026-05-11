"""`PROVIDER_ENTITY`: single declaration of the provider resource.

Read by:
  - `src/api/routes/providers.py` — derives `PROVIDER_SPEC` for the
    mount helpers and reads the list filters from `.filters`.
  - `src/logic/providers/provider_processing.py` — reads
    `PROVIDER_ENTITY.audit` for the `mutate(...)` resource binding.
  - `src/specs/provider_licensure.py` /
    `provider_education.py` / `provider_certification.py` — set
    ``parent=PROVIDER_ENTITY`` so the mount layer's parent-chain
    machinery builds nested paths like
    ``/providers/{provider_id}/licensures/{licensure_id}``.
  - `src/specs/user.py` — the related-list subresource
    `RelatedListSubresource(child_spec=PROVIDER_ENTITY.to_resource_spec(), ...)`
    on the user spec; closes the `api/common -> api/routes`
    inversion documented in A1 (#317).
"""

from typing import Final

from src.framework.dependencies import get_provider_repository
from src.framework.entity_spec import (
    AUTHENTICATED,
    OWNER_OR_ADMIN,
    EntitySpec,
    Redirects,
    RouteSet,
)
from src.framework.resource_routes import QueryParam
from src.models import Provider
from src.models.enums import (
    CERTIFICATION_TYPES,
    CERTIFICATION_TYPES_LABELS,
    EDUCATION_TYPES,
    EDUCATION_TYPES_LABELS,
    LICENSE_TYPES,
    LICENSE_TYPES_LABELS,
)
from src.repositories.favorites.user_favorite_repository import UserFavoriteRepository
from src.schemas.providers.provider import (
    ProviderCreate,
    ProviderRead,
    ProviderUpdate,
)

# After create or update, redirect to the edit form so the user can
# keep editing the parent + its credentials. The same callable is reused
# by the three credential subentities (their parent is this provider).
_provider_form_redirect = Redirects.to_edit_form("providers", "provider_id")


PROVIDER_ENTITY: Final[EntitySpec] = EntitySpec(
    name="provider",
    url_collection="providers",
    id_param="provider_id",
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
    ),
    filters=(
        QueryParam("license_type", str | None, None),
        QueryParam("issuing_state", str | None, None),
    ),
    create_redirect=_provider_form_redirect,
    update_redirect=_provider_form_redirect,
    # Per-viewer detail extras live on the spec — see `EntitySpec`.
    detail_extras_path="src.logic.providers.provider_processing.provider_detail_extras",
    detail_extras_repos=(("user_favorite_repo", UserFavoriteRepository),),
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
