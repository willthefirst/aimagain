from src.domain.specs.provider import PROVIDER_ENTITY
from src.domain.specs.provider_certification import CERTIFICATION_ENTITY
from src.domain.specs.provider_education import EDUCATION_ENTITY
from src.domain.specs.provider_licensure import LICENSURE_ENTITY
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(PROVIDER_ENTITY)


# Every verb auto-binds. The Provider's two per-spec hooks both live
# on `PROVIDER_ENTITY` and the framework wires them in automatically:
#
#   - `form_extras_path` (#533) drives the per-viewer Org-picker
#     dropdown on the create/edit forms; the framework threads
#     `OrganizationRepository` into the factory-built form handlers
#     via `form_extras_repos`.
#   - `payload_authz_path` (#532) gates `POST /providers` and
#     `PATCH /providers/{id}` so the requesting user can only attach
#     to an Org they own (replaces the bespoke
#     `handle_create_provider` / `handle_update_provider` shim PR #531
#     introduced before the framework hook existed).
#
# Per-viewer detail extras (`provider_detail_extras` + the user-favorite
# repo it needs) live on the spec via the same dotted-path late-binding.
# Owned credential subentities (licensure, education, certification)
# self-register on `PROVIDER_ENTITY.children` and pick up the same
# auto-bind for their create / update / delete factories.
mount_entity(
    router,
    PROVIDER_ENTITY,
    owned_subentities=(LICENSURE_ENTITY, EDUCATION_ENTITY, CERTIFICATION_ENTITY),
)
