"""`CERTIFICATION_ENTITY`: provider's certification credential subentity.

Owned subentity of `Provider`. See `_credential.py` for the shared
factory (parent chain, subrow-CRUD-only routes, parent-form redirect).
"""

from typing import Final

from src.api.common.entity_spec import EntitySpec
from src.api.common.specs._credential import make_provider_credential_entity
from src.models import ProviderCertification
from src.schemas.providers.provider import (
    ProviderCertificationAuditSnapshot,
    ProviderCertificationRead,
    certification_create_adapter,
    certification_update_adapter,
)

CERTIFICATION_ENTITY: Final[EntitySpec] = make_provider_credential_entity(
    name="provider_certification",
    url_collection="certifications",
    id_param="certification_id",
    model=ProviderCertification,
    audit_stem="certification",
    snapshot_schema=ProviderCertificationAuditSnapshot,
    read_schema=ProviderCertificationRead,
    create_adapter=certification_create_adapter,
    update_adapter=certification_update_adapter,
)
