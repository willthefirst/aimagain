from src.domain.specs import POST_ENTITY
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(POST_ENTITY)


# Whole-supertype face of the polymorphic post entity — one URL family
# (`/posts`) lists every kind. `?kind=<value>` selects the create-form
# template at `GET /posts/form`; the discriminated-union body adapter
# dispatches POST/PATCH bodies by their declared `kind`.
mount_entity(router, POST_ENTITY)
