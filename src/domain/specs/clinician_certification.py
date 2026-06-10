"""`CERTIFICATION_ENTITY`: clinician's certification credential subentity.

Owned subentity of `Clinician`. See `_credential.py` for the shared
factory (parent chain, subrow-CRUD-only routes, parent-form redirect).
"""

from typing import Final

from src.domain.logic.clinicians.schema import (
    ClinicianCertificationCreate,
    ClinicianCertificationRead,
    ClinicianCertificationUpdate,
)
from src.domain.models import ClinicianCertification
from src.domain.specs._credential import make_clinician_credential_entity
from src.domain.specs.clinician import _clinician_certifications_list_redirect
from src.framework.dispatch.entity_spec import EntitySpec

CERTIFICATION_ENTITY: Final[EntitySpec] = make_clinician_credential_entity(
    name="clinician_certification",
    url_collection="certifications",
    id_param="certification_id",
    model=ClinicianCertification,
    audit_stem="certification",
    read_schema=ClinicianCertificationRead,
    create_adapter=ClinicianCertificationCreate,
    update_adapter=ClinicianCertificationUpdate,
    mutation_redirect=_clinician_certifications_list_redirect,
)
