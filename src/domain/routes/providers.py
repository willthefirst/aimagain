from src.domain.logic.providers.handlers import (
    handle_create_provider,
    handle_update_provider,
)
from src.domain.specs.provider import PROVIDER_ENTITY
from src.domain.specs.provider_certification import CERTIFICATION_ENTITY
from src.domain.specs.provider_education import EDUCATION_ENTITY
from src.domain.specs.provider_licensure import LICENSURE_ENTITY
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(PROVIDER_ENTITY)


# Every verb auto-binds except `create` and `update`, which are
# overridden so the wire-level POST/PATCH reject `org_id` values
# pointing at Orgs the user doesn't own (#524). The create/edit form's
# per-viewer Org-picker dropdown is now driven by
# `form_extras_path` on the spec (#533) — the framework threads the
# `OrganizationRepository` into the factory-built form handlers via
# `form_extras_repos`. Per-viewer detail extras
# (`provider_detail_extras` + the user-favorite repo it needs) live on
# the spec via the same dotted-path late-binding. Owned credential
# subentities (licensure, education, certification) self-register on
# `PROVIDER_ENTITY.children` and pick up the same auto-bind for their
# create / update / delete factories.
mount_entity(
    router,
    PROVIDER_ENTITY,
    handlers={
        "create": handle_create_provider,
        "update": handle_update_provider,
    },
    owned_subentities=(LICENSURE_ENTITY, EDUCATION_ENTITY, CERTIFICATION_ENTITY),
)
