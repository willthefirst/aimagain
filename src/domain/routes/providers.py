from src.domain.specs.affiliation import AFFILIATION_ENTITY  # noqa: F401
from src.domain.specs.provider import PROVIDER_ENTITY
from src.domain.specs.provider_certification import CERTIFICATION_ENTITY  # noqa: F401
from src.domain.specs.provider_education import EDUCATION_ENTITY  # noqa: F401
from src.domain.specs.provider_licensure import LICENSURE_ENTITY  # noqa: F401
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(PROVIDER_ENTITY)


# Owned subentities — affiliations (clinician × org practice-role rows,
# inline list on the edit page, #642 PR 1) and the three credential
# sub-tables (person-level, FK to `clinicians.id` after #635 PR A) —
# self-register on `PROVIDER_ENTITY.children` at spec-construction time
# (each child spec declares `parent=PROVIDER_ENTITY`). `mount_entity`
# defaults `owned_subentities=entity.children`, so the `noqa: F401`
# imports above are the only thing needed: they trigger each child
# spec's module-load side effect (registration), and the parent
# mount picks them up automatically.
mount_entity(router, PROVIDER_ENTITY)
