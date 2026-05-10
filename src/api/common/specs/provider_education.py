"""`EDUCATION_ENTITY`: provider's education credential subentity.

Owned subentity of `Provider`. See `provider_licensure.py` for the
pattern (parent chain, subrow-CRUD-only routes, parent-form redirect).
"""

from typing import Final

from src.api.common.entity_spec import EntitySpec, RouteSet
from src.api.common.specs.provider import PROVIDER_ENTITY, _provider_form_redirect
from src.auth_config import current_active_user
from src.logic._authz import assert_owner_or_admin
from src.logic.audit import AuditAction, AuditedResource, make_snapshotter
from src.models import ProviderEducation
from src.repositories.dependencies import get_provider_repository
from src.schemas.providers.provider import (
    ProviderEducationAuditSnapshot,
    ProviderEducationRead,
    education_create_adapter,
    education_update_adapter,
)

EDUCATION_AUDITED_RESOURCE: Final[AuditedResource] = AuditedResource(
    type="provider_education",
    snapshot=make_snapshotter(ProviderEducationAuditSnapshot),
    create=AuditAction.CREATE_EDUCATION,
    update=AuditAction.UPDATE_EDUCATION,
    delete=AuditAction.DELETE_EDUCATION,
)


def _education_read_to_dict(row: ProviderEducation) -> dict:
    return ProviderEducationRead.model_validate(row).model_dump(mode="json")


EDUCATION_ENTITY: Final[EntitySpec] = EntitySpec(
    name="provider_education",
    url_collection="educations",
    id_param="education_id",
    model=ProviderEducation,
    parent=PROVIDER_ENTITY,
    repo_dep=get_provider_repository,
    write_user_dep=current_active_user,
    write_authz=assert_owner_or_admin,
    audit=EDUCATION_AUDITED_RESOURCE,
    create_adapter=education_create_adapter,
    update_adapter=education_update_adapter,
    read_to_dict=_education_read_to_dict,
    routes=RouteSet(create=True, update=True, delete=True),
    create_redirect=_provider_form_redirect,
    update_redirect=_provider_form_redirect,
    delete_redirect=_provider_form_redirect,
)
