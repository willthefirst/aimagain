from src.domain.specs.provider import PROVIDER_ENTITY
from src.domain.specs.provider_certification import CERTIFICATION_ENTITY
from src.domain.specs.provider_education import EDUCATION_ENTITY
from src.domain.specs.provider_licensure import LICENSURE_ENTITY
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(PROVIDER_ENTITY)


# Owned credential subentities (licensure, education, certification)
# self-register on `PROVIDER_ENTITY.children` and pick up the framework's
# create / update / delete factories.
mount_entity(
    router,
    PROVIDER_ENTITY,
    owned_subentities=(LICENSURE_ENTITY, EDUCATION_ENTITY, CERTIFICATION_ENTITY),
)
