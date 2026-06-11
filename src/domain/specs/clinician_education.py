"""`EDUCATION_ENTITY`: clinician's education credential subentity.

Owned subentity of `Clinician`. Migrated to the canonical resource
pattern (PR 3): dedicated list / create / edit pages at
``/clinicians/{id}/educations`` instead of an inline add form on the
list page. See `_credential.py` for the shared factory shape.
"""

from typing import Final

from src.domain.logic.clinicians.schema import (
    ClinicianEducationCreate,
    ClinicianEducationRead,
    ClinicianEducationUpdate,
)
from src.domain.models import ClinicianEducation
from src.domain.models.enums import EDUCATION_TYPES, EDUCATION_TYPES_LABELS
from src.domain.specs._credential import (
    CANONICAL_CREDENTIAL_ROUTES,
    make_clinician_credential_entity,
)
from src.domain.specs.clinician import _clinician_educations_list_redirect
from src.framework.dispatch.entity_spec import EntitySpec

EDUCATION_ENTITY: Final[EntitySpec] = make_clinician_credential_entity(
    name="clinician_education",
    singular_label="education",
    url_collection="educations",
    id_param="education_id",
    model=ClinicianEducation,
    audit_stem="education",
    read_schema=ClinicianEducationRead,
    create_adapter=ClinicianEducationCreate,
    update_adapter=ClinicianEducationUpdate,
    mutation_redirect=_clinician_educations_list_redirect,
    routes=CANONICAL_CREDENTIAL_ROUTES,
    static_context={
        "EDUCATION_TYPES": EDUCATION_TYPES,
        "EDUCATION_TYPES_LABELS": EDUCATION_TYPES_LABELS,
    },
)
