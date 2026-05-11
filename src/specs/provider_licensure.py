"""`LICENSURE_ENTITY`: provider's licensure credential subentity.

Owned subentity of `Provider`: routes nest under
``/providers/{provider_id}/licensures/{licensure_id}``. Shape is
identical to the other provider credentials — see `_credential.py`
for the shared factory.

Read by `src/api/routes/providers.py` (derives `LICENSURE_SPEC` for
the mount helpers) and `src/logic/providers/provider_processing.py`
(reads `LICENSURE_ENTITY.audit` for the `mutate(...)` binding).
"""

from typing import Final

from src.api.common.entity_spec import EntitySpec
from src.models import ProviderLicensure
from src.schemas.providers.provider import (
    ProviderLicensureCreate,
    ProviderLicensureRead,
    ProviderLicensureUpdate,
)
from src.specs._credential import make_provider_credential_entity

LICENSURE_ENTITY: Final[EntitySpec] = make_provider_credential_entity(
    name="provider_licensure",
    url_collection="licensures",
    id_param="licensure_id",
    model=ProviderLicensure,
    audit_stem="licensure",
    read_schema=ProviderLicensureRead,
    create_adapter=ProviderLicensureCreate,
    update_adapter=ProviderLicensureUpdate,
)
