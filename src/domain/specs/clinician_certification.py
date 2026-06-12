"""`CERTIFICATION_ENTITY`: clinician's certification credential subentity.

Owned subentity of `Clinician`. Migrated to the canonical resource
pattern (PR 3): dedicated list / create / edit pages at
``/clinicians/{id}/certifications`` instead of an inline add form on
the list page. See `_credential.py` for the shared factory shape and
`clinician_licensure.py` for the first credential to undergo the
conversion.
"""

from typing import Final

from src.domain.logic.clinicians.schema import (
    ClinicianCertificationCreate,
    ClinicianCertificationRead,
    ClinicianCertificationUpdate,
)
from src.domain.models import ClinicianCertification
from src.domain.models.enums import CERTIFICATION_TYPES, CERTIFICATION_TYPES_LABELS
from src.domain.specs._credential import (
    CANONICAL_CREDENTIAL_ROUTES,
    make_clinician_credential_entity,
)
from src.domain.specs.clinician import _clinician_certifications_list_redirect
from src.framework.dispatch.entity_spec import EntitySpec

CERTIFICATION_ENTITY: Final[EntitySpec] = make_clinician_credential_entity(
    name="clinician_certification",
    singular_label="certification",
    url_collection="certifications",
    id_param="certification_id",
    model=ClinicianCertification,
    audit_stem="certification",
    read_schema=ClinicianCertificationRead,
    create_adapter=ClinicianCertificationCreate,
    update_adapter=ClinicianCertificationUpdate,
    mutation_redirect=_clinician_certifications_list_redirect,
    routes=CANONICAL_CREDENTIAL_ROUTES,
    static_context={
        "CERTIFICATION_TYPES": CERTIFICATION_TYPES,
        "CERTIFICATION_TYPES_LABELS": CERTIFICATION_TYPES_LABELS,
    },
    form_partial="certifications/_form_certification.html",
)
