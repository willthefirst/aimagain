"""`LICENSURE_ENTITY`: clinician's licensure credential subentity.

Owned subentity of `Clinician`: routes nest under
``/clinicians/{clinician_id}/licensures/{licensure_id}``. Shape is
identical to the other clinician credentials — see `_credential.py`
for the shared factory.

Read by `src/domain/routes/clinicians.py` (derives `LICENSURE_SPEC` for
the mount helpers).
"""

from typing import Final

from src.domain.logic.clinicians.schema import (
    ClinicianLicensureCreate,
    ClinicianLicensureRead,
    ClinicianLicensureUpdate,
)
from src.domain.models import ClinicianLicensure
from src.domain.specs._credential import make_clinician_credential_entity
from src.framework.dispatch.entity_spec import EntitySpec

LICENSURE_ENTITY: Final[EntitySpec] = make_clinician_credential_entity(
    name="clinician_licensure",
    url_collection="licensures",
    id_param="licensure_id",
    model=ClinicianLicensure,
    audit_stem="licensure",
    read_schema=ClinicianLicensureRead,
    create_adapter=ClinicianLicensureCreate,
    update_adapter=ClinicianLicensureUpdate,
)
