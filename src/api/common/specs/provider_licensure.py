"""`LICENSURE_ENTITY`: provider's licensure credential subentity.

Owned subentity of `Provider`: routes nest under
``/providers/{provider_id}/licensures/{licensure_id}``. `parent` on
the spec carries the link; `EntitySpec.to_resource_spec()` walks the
chain so the mount layer's existing parent-chain machinery builds
the path.

Read by `src/api/routes/providers.py` (derives `LICENSURE_SPEC` for
the mount helpers) and `src/logic/providers/provider_processing.py`
(reads `LICENSURE_ENTITY.audit` for the `mutate(...)` binding).
"""

from typing import Final

from src.api.common.entity_spec import EntitySpec, RouteSet
from src.api.common.specs.provider import PROVIDER_ENTITY, _provider_form_redirect
from src.auth_config import current_active_user
from src.logic._authz import assert_owner_or_admin
from src.logic.audit import AuditAction, AuditedResource, make_snapshotter
from src.models import ProviderLicensure
from src.repositories.dependencies import get_provider_repository
from src.schemas.providers.provider import (
    ProviderLicensureAuditSnapshot,
    ProviderLicensureRead,
    licensure_create_adapter,
    licensure_update_adapter,
)

LICENSURE_AUDITED_RESOURCE: Final[AuditedResource] = AuditedResource(
    type="provider_licensure",
    snapshot=make_snapshotter(ProviderLicensureAuditSnapshot),
    create=AuditAction.CREATE_LICENSURE,
    update=AuditAction.UPDATE_LICENSURE,
    delete=AuditAction.DELETE_LICENSURE,
)


def _licensure_read_to_dict(row: ProviderLicensure) -> dict:
    return ProviderLicensureRead.model_validate(row).model_dump(mode="json")


LICENSURE_ENTITY: Final[EntitySpec] = EntitySpec(
    name="provider_licensure",
    url_collection="licensures",
    id_param="licensure_id",
    model=ProviderLicensure,
    parent=PROVIDER_ENTITY,
    repo_dep=get_provider_repository,
    write_user_dep=current_active_user,
    write_authz=assert_owner_or_admin,
    audit=LICENSURE_AUDITED_RESOURCE,
    create_adapter=licensure_create_adapter,
    update_adapter=licensure_update_adapter,
    read_to_dict=_licensure_read_to_dict,
    # Subrow CRUD only — sub-rows aren't independently listed or
    # detailed (they only appear in the parent provider's pages).
    routes=RouteSet(create=True, update=True, delete=True),
    # Sub-row mutations send HTMX clients back to the parent edit
    # form so the user can keep editing.
    create_redirect=_provider_form_redirect,
    update_redirect=_provider_form_redirect,
    delete_redirect=_provider_form_redirect,
)
