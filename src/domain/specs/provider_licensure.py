"""`LICENSURE_ENTITY`: clinician's licensure credential subentity.

Owned subentity of `Clinician`: routes nest under
``/clinicians/{clinician_id}/licensures/{licensure_id}`` (URL family
renamed in #642 PR 4; model class stays `ProviderLicensure`). Shape is
identical to the other clinician credentials — see `_credential.py`
for the shared factory.

Read by `src/domain/routes/clinicians.py` (derives `LICENSURE_SPEC` for
the mount helpers).
"""

from typing import Final

from src.domain.logic.clinicians.schema import (
    ProviderLicensureCreate,
    ProviderLicensureRead,
    ProviderLicensureUpdate,
)
from src.domain.models import ProviderLicensure
from src.domain.specs._credential import make_provider_credential_entity
from src.framework.dispatch.entity_spec import EntitySpec

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
