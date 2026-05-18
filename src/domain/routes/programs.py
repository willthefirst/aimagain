from src.domain.specs.program import PROGRAM_ENTITY
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(PROGRAM_ENTITY)


# The two per-spec hooks both live on ``PROGRAM_ENTITY`` and the
# framework wires them in automatically:
#
#   - ``form_extras_path`` (#534) drives the per-viewer Org-picker
#     dropdown on the create/edit forms; the framework threads
#     ``OrganizationRepository`` into the factory-built form handlers
#     via ``form_extras_repos``.
#   - ``payload_authz_path`` (#535) gates ``POST /programs`` and
#     ``PATCH /programs/{id}`` so the requesting user can only attach
#     to an Org they own.
#
# A single ``mount_entity`` line — no ``handlers={...}`` overrides — is
# the conformance check that PR #534 + #535 fully generalized PR 3's
# bespoke-handler workaround.
mount_entity(router, PROGRAM_ENTITY)
