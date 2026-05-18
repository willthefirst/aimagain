from src.domain.specs.organization import ORGANIZATION_ENTITY
from src.framework.dispatch.registry import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(ORGANIZATION_ENTITY)


mount_entity(router, ORGANIZATION_ENTITY)
