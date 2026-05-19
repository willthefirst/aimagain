from src.domain.specs.affiliation import AFFILIATION_ENTITY
from src.domain.specs.provider import PROVIDER_ENTITY
from src.domain.specs.provider_certification import CERTIFICATION_ENTITY
from src.domain.specs.provider_education import EDUCATION_ENTITY
from src.domain.specs.provider_licensure import LICENSURE_ENTITY
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(PROVIDER_ENTITY)


# Owned subentities: affiliations (clinician × org practice-role rows,
# inline list on the edit page, #642 PR 1) and the three credential
# sub-tables (person-level, FK to `clinicians.id` after #635 PR A).
# Each self-registers on `PROVIDER_ENTITY.children` and picks up the
# framework's create / update / delete factories at mount time.
mount_entity(
    router,
    PROVIDER_ENTITY,
    owned_subentities=(
        AFFILIATION_ENTITY,
        LICENSURE_ENTITY,
        EDUCATION_ENTITY,
        CERTIFICATION_ENTITY,
    ),
)
