from src.domain.logic.clinicians.handlers import (
    handle_list_clinician_certifications,
    handle_list_clinician_educations,
    handle_list_clinician_licensures,
)
from src.domain.specs.clinician import CLINICIAN_ENTITY
from src.domain.specs.clinician_affiliation import (  # noqa: F401
    CLINICIAN_AFFILIATION_ENTITY,
)
from src.domain.specs.clinician_certification import CERTIFICATION_ENTITY  # noqa: F401
from src.domain.specs.clinician_education import EDUCATION_ENTITY  # noqa: F401
from src.domain.specs.clinician_licensure import LICENSURE_ENTITY  # noqa: F401
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(CLINICIAN_ENTITY)


# Owned subentities — affiliations (clinician × org practice-role rows,
# inline list on the edit page, #642 PR 1) and the three credential
# sub-tables (person-level, FK to `clinicians.id` after #635 PR A) —
# self-register on `CLINICIAN_ENTITY.children` at spec-construction time
# (each child spec declares `parent=CLINICIAN_ENTITY`). `mount_entity`
# defaults `owned_subentities=entity.children`, so the `noqa: F401`
# imports above are the only thing needed: they trigger each child
# spec's module-load side effect (registration), and the parent
# mount picks them up automatically.
#
# Bespoke list handlers for the canonical-pattern credentials: each
# loads the parent clinician and returns its eager-loaded credential
# list. The default `make_list_handler` would route through
# `handle_list` which needs a `list_<collection>(<parent_id>=...)`
# repo method we don't have for credentials. form_new and form_edit
# auto-bind to the factory makers.
mount_entity(
    router,
    CLINICIAN_ENTITY,
    handlers={
        "clinician_licensure.list": handle_list_clinician_licensures,
        "clinician_education.list": handle_list_clinician_educations,
        "clinician_certification.list": handle_list_clinician_certifications,
    },
)
