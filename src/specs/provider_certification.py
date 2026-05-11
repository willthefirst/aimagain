"""`CERTIFICATION_ENTITY`: provider's certification credential subentity.

Owned subentity of `Provider`. See `_credential.py` for the shared
factory (parent chain, subrow-CRUD-only routes, parent-form redirect).
"""

from typing import Final

from src.api.common.entity_spec import EntitySpec
from src.models import ProviderCertification
from src.schemas.providers.provider import (
    ProviderCertificationCreate,
    ProviderCertificationRead,
    ProviderCertificationUpdate,
)
from src.specs._credential import make_provider_credential_entity

CERTIFICATION_ENTITY: Final[EntitySpec] = make_provider_credential_entity(
    name="provider_certification",
    url_collection="certifications",
    id_param="certification_id",
    model=ProviderCertification,
    audit_stem="certification",
    read_schema=ProviderCertificationRead,
    create_adapter=ProviderCertificationCreate,
    update_adapter=ProviderCertificationUpdate,
)
