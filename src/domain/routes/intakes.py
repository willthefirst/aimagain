from src.domain.specs.posts import INTAKE_ENTITY
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(INTAKE_ENTITY)

# See `referrals.py` — same shape, locked to `kind='intake'`.
mount_entity(router, INTAKE_ENTITY)
