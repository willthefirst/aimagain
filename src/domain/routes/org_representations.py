"""Route mount for `OrgRepresentation` — User↔Org authority (Claim B).

Thin: spec-driven. `mount_entity` reads `ORG_REPRESENTATION_ENTITY` and
binds the framework's `make_create_handler` / `make_update_handler` /
`make_delete_handler` factories, plus the `authority` state-axis
(resolved lazily via the spec's `handler_path`).
"""

from src.domain.specs.org_representation import ORG_REPRESENTATION_ENTITY
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(ORG_REPRESENTATION_ENTITY)


mount_entity(router, ORG_REPRESENTATION_ENTITY)
