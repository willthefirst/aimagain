"""Route mount for `OrgRepresentation` — User↔Org authority (Claim B).

Thin spec-driven mount. The spec declares `payload_authz_path` and
`after_create_path` so the framework's generic create handler does the
right per-authority-method dispatch (auto-verify, append Verification
event) — no bespoke route handler needed. State-axis and update/delete
flow through `mount_entity` unchanged.
"""

from src.domain.specs.org_representation import ORG_REPRESENTATION_ENTITY
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(ORG_REPRESENTATION_ENTITY)


mount_entity(router, ORG_REPRESENTATION_ENTITY)
