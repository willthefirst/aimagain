from src.domain.specs.posts import OPENING_ENTITY
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(OPENING_ENTITY)

# See `referrals.py` — same shape, locked to `kind='opening'`.
mount_entity(router, OPENING_ENTITY)
