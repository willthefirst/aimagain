"""`LICENSURE_ENTITY`: provider's licensure credential subentity.

Owned subentity of `Provider`: routes nest under
``/providers/{provider_id}/licensures/{licensure_id}``. Shape is
identical to the other provider credentials — see `_credential.py`
for the shared factory.

Read by `src/domain/routes/providers.py` (derives `LICENSURE_SPEC` for
the mount helpers) and `src/logic/providers/provider_processing.py`
(reads `LICENSURE_ENTITY.audit` for the `mutate(...)` binding).
"""

from typing import Final

from src.domain.logic.providers.schema import (
    ProviderLicensureCreate,
    ProviderLicensureRead,
    ProviderLicensureUpdate,
)
from src.domain.models import ProviderLicensure
from src.domain.specs._credential import make_provider_credential_entity
from src.framework.entity_spec import EntitySpec

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
