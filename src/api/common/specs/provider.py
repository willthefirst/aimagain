"""`PROVIDER_ENTITY`: single declaration of the provider resource.

Read by:
  - `src/api/routes/providers.py` — derives `PROVIDER_SPEC` for the
    mount helpers and reads the list filters from `.filters`.
  - `src/logic/providers/provider_processing.py` — reads
    `PROVIDER_ENTITY.audit` for the `mutate(...)` resource binding.
  - `src/api/common/specs/provider_licensure.py` /
    `provider_education.py` / `provider_certification.py` — set
    ``parent=PROVIDER_ENTITY`` so the mount layer's parent-chain
    machinery builds nested paths like
    ``/providers/{provider_id}/licensures/{licensure_id}``.
  - `src/api/common/specs/user.py` — the related-list subresource
    `RelatedListSubresource(child_spec=PROVIDER_ENTITY.to_resource_spec(), ...)`
    on the user spec; closes the `api/common -> api/routes`
    inversion documented in A1 (#317).
"""

from typing import Final

from src.api.common.entity_spec import OWNER_OR_ADMIN, EntitySpec, Redirects, RouteSet
from src.api.common.resource_routes import QueryParam
from src.auth_config import current_active_user
from src.models import Provider
from src.repositories.dependencies import get_provider_repository
from src.schemas.providers.provider import (
    ProviderAuditSnapshot,
    ProviderRead,
    provider_create_adapter,
    provider_update_adapter,
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
    read_user_dep=current_active_user,
    write_user_dep=current_active_user,
    auth_policy=OWNER_OR_ADMIN,
    audit_snapshot=ProviderAuditSnapshot,
    create_adapter=provider_create_adapter,
    update_adapter=provider_update_adapter,
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
)
