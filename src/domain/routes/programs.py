from src.domain.specs.program import PROGRAM_ENTITY
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(PROGRAM_ENTITY)


mount_entity(router, PROGRAM_ENTITY)
