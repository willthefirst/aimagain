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

from src.api.common.entity_spec import EntitySpec, RouteSet, Templates
from src.api.common.resource_routes import QueryParam
from src.auth_config import current_active_user
from src.logic._authz import assert_owner_or_admin
from src.logic.audit import AuditAction, AuditedResource, make_snapshotter
from src.models import Provider
from src.repositories.dependencies import get_provider_repository
from src.schemas.providers.provider import (
    ProviderAuditSnapshot,
    ProviderRead,
    provider_create_adapter,
    provider_update_adapter,
)

PROVIDER_AUDITED_RESOURCE: Final[AuditedResource] = AuditedResource(
    type="provider",
    snapshot=make_snapshotter(ProviderAuditSnapshot),
    create=AuditAction.CREATE_PROVIDER,
    update=AuditAction.UPDATE_PROVIDER,
    delete=AuditAction.DELETE_PROVIDER,
)


def _provider_read_to_dict(provider: Provider) -> dict:
    return ProviderRead.model_validate(provider).model_dump(mode="json")


def _provider_form_redirect(*, provider_id, **_) -> str:
    """After create or update, redirect to the edit form so the user
    can keep editing the parent + its credentials."""
    return f"/providers/{provider_id}/form"


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
    write_authz=assert_owner_or_admin,
    audit=PROVIDER_AUDITED_RESOURCE,
    create_adapter=provider_create_adapter,
    update_adapter=provider_update_adapter,
    read_to_dict=_provider_read_to_dict,
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
    templates=Templates(
        list="providers/list.html",
        detail="providers/detail.html",
    ),
)
