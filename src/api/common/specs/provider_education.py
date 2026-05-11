"""`EDUCATION_ENTITY`: provider's education credential subentity.

Owned subentity of `Provider`. See `_credential.py` for the shared
factory (parent chain, subrow-CRUD-only routes, parent-form redirect).
"""

from typing import Final

from src.api.common.entity_spec import EntitySpec
from src.api.common.specs._credential import make_provider_credential_entity
from src.models import ProviderEducation
from src.schemas.providers.provider import (
    ProviderEducationAuditSnapshot,
    ProviderEducationRead,
    education_create_adapter,
    education_update_adapter,
)

EDUCATION_ENTITY: Final[EntitySpec] = make_provider_credential_entity(
    name="provider_education",
    url_collection="educations",
    id_param="education_id",
    model=ProviderEducation,
    audit_stem="education",
    snapshot_schema=ProviderEducationAuditSnapshot,
    read_schema=ProviderEducationRead,
    create_adapter=education_create_adapter,
    update_adapter=education_update_adapter,
)
