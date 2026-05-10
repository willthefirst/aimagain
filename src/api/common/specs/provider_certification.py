"""`CERTIFICATION_ENTITY`: provider's certification credential subentity.

Owned subentity of `Provider`. See `provider_licensure.py` for the
pattern (parent chain, subrow-CRUD-only routes, parent-form redirect).
"""

from typing import Final

from src.api.common.entity_spec import EntitySpec, RouteSet
from src.api.common.specs.provider import PROVIDER_ENTITY, _provider_form_redirect
from src.auth_config import current_active_user
from src.logic._authz import assert_owner_or_admin
from src.logic.audit import AuditAction, AuditedResource, make_snapshotter
from src.models import ProviderCertification
from src.repositories.dependencies import get_provider_repository
from src.schemas.providers.provider import (
    ProviderCertificationAuditSnapshot,
    ProviderCertificationRead,
    certification_create_adapter,
    certification_update_adapter,
)

CERTIFICATION_AUDITED_RESOURCE: Final[AuditedResource] = AuditedResource(
    type="provider_certification",
    snapshot=make_snapshotter(ProviderCertificationAuditSnapshot),
    create=AuditAction.CREATE_CERTIFICATION,
    update=AuditAction.UPDATE_CERTIFICATION,
    delete=AuditAction.DELETE_CERTIFICATION,
)


def _certification_read_to_dict(row: ProviderCertification) -> dict:
    return ProviderCertificationRead.model_validate(row).model_dump(mode="json")


CERTIFICATION_ENTITY: Final[EntitySpec] = EntitySpec(
    name="provider_certification",
    url_collection="certifications",
    id_param="certification_id",
    model=ProviderCertification,
    parent=PROVIDER_ENTITY,
    repo_dep=get_provider_repository,
    write_user_dep=current_active_user,
    write_authz=assert_owner_or_admin,
    audit=CERTIFICATION_AUDITED_RESOURCE,
    create_adapter=certification_create_adapter,
    update_adapter=certification_update_adapter,
    read_to_dict=_certification_read_to_dict,
    routes=RouteSet(create=True, update=True, delete=True),
    create_redirect=_provider_form_redirect,
    update_redirect=_provider_form_redirect,
    delete_redirect=_provider_form_redirect,
)
