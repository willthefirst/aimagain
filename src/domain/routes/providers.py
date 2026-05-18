from src.domain.logic.providers.handlers import (
    handle_create_provider,
    handle_get_provider_edit_form,
    handle_get_provider_new_form,
    handle_update_provider,
)
from src.domain.specs.provider import PROVIDER_ENTITY
from src.domain.specs.provider_certification import CERTIFICATION_ENTITY
from src.domain.specs.provider_education import EDUCATION_ENTITY
from src.domain.specs.provider_licensure import LICENSURE_ENTITY
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(PROVIDER_ENTITY)


# Every verb auto-binds except `create`, `update`, `form_new`, and
# `form_edit`, which are overridden so the Provider create/edit form
# can render an Org-picker dropdown scoped to the requesting user's
# Organizations and so the wire-level POST/PATCH reject `org_id`
# values pointing at Orgs the user doesn't own (#524). Per-viewer
# detail extras (`provider_detail_extras` + the user-favorite repo
# it needs) live on the spec via dotted-path late-binding. Owned
# credential subentities (licensure, education, certification)
# self-register on `PROVIDER_ENTITY.children` and pick up the same
# auto-bind for their create / update / delete factories.
mount_entity(
    router,
    PROVIDER_ENTITY,
    handlers={
        "create": handle_create_provider,
        "update": handle_update_provider,
        "form_new": handle_get_provider_new_form,
        "form_edit": handle_get_provider_edit_form,
    },
    owned_subentities=(LICENSURE_ENTITY, EDUCATION_ENTITY, CERTIFICATION_ENTITY),
)
