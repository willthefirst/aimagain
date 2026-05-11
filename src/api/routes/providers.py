from src.api.common import make_entity_router
from src.api.common.resource_routes import mount_entity
from src.api.common.specs.provider import PROVIDER_ENTITY
from src.api.common.specs.provider_certification import CERTIFICATION_ENTITY
from src.api.common.specs.provider_education import EDUCATION_ENTITY
from src.api.common.specs.provider_licensure import LICENSURE_ENTITY
from src.logic.providers.provider_processing import handle_get_provider_form

router = make_entity_router(PROVIDER_ENTITY)
providers_api_router = router.router


# Only `form_new` stays bespoke (the create-form template needs the
# Pydantic class as a Jinja field-resolver). Every other verb auto-binds:
# `create` reads `PROVIDER_ENTITY.children` to append inline credential
# rows; `list` echoes filter selections; detail/update/delete/form_edit
# go through the standard factories. Per-viewer detail extras
# (`provider_detail_extras` + the user-favorite repo it needs) live on
# the spec via dotted-path late-binding. Owned credential subentities
# (licensure, education, certification) self-register on
# `PROVIDER_ENTITY.children` and pick up the same auto-bind for their
# create / update / delete factories.
mount_entity(
    router,
    PROVIDER_ENTITY,
    handlers={
        "form_new": handle_get_provider_form,
    },
    owned_subentities=(LICENSURE_ENTITY, EDUCATION_ENTITY, CERTIFICATION_ENTITY),
)
