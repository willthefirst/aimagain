from src.domain.specs.organization import ORGANIZATION_ENTITY
from src.framework import make_entity_router
from src.framework.dispatch.resource_routes import mount_entity

router = make_entity_router(ORGANIZATION_ENTITY)
organizations_api_router = router.router


mount_entity(router, ORGANIZATION_ENTITY)
