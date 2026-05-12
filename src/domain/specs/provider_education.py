"""`EDUCATION_ENTITY`: provider's education credential subentity.

Owned subentity of `Provider`. See `_credential.py` for the shared
factory (parent chain, subrow-CRUD-only routes, parent-form redirect).
"""

from typing import Final

from src.domain.logic.providers.schema import (
    ProviderEducationCreate,
    ProviderEducationRead,
    ProviderEducationUpdate,
)
from src.domain.models import ProviderEducation
from src.domain.specs._credential import make_provider_credential_entity
from src.framework.entity_spec import EntitySpec

EDUCATION_ENTITY: Final[EntitySpec] = make_provider_credential_entity(
    name="provider_education",
    url_collection="educations",
    id_param="education_id",
    model=ProviderEducation,
    audit_stem="education",
    read_schema=ProviderEducationRead,
    create_adapter=ProviderEducationCreate,
    update_adapter=ProviderEducationUpdate,
)
