"""`EDUCATION_ENTITY`: clinician's education credential subentity.

Owned subentity of `Clinician`. See `_credential.py` for the shared
factory (parent chain, subrow-CRUD-only routes, parent-form redirect).
"""

from typing import Final

from src.domain.logic.clinicians.schema import (
    ClinicianEducationCreate,
    ClinicianEducationRead,
    ClinicianEducationUpdate,
)
from src.domain.models import ClinicianEducation
from src.domain.specs._credential import make_clinician_credential_entity
from src.framework.dispatch.entity_spec import EntitySpec

EDUCATION_ENTITY: Final[EntitySpec] = make_clinician_credential_entity(
    name="clinician_education",
    url_collection="educations",
    id_param="education_id",
    model=ClinicianEducation,
    audit_stem="education",
    read_schema=ClinicianEducationRead,
    create_adapter=ClinicianEducationCreate,
    update_adapter=ClinicianEducationUpdate,
)
