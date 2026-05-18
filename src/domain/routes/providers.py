from src.domain.specs.provider import PROVIDER_ENTITY
from src.domain.specs.provider_certification import CERTIFICATION_ENTITY
from src.domain.specs.provider_education import EDUCATION_ENTITY
from src.domain.specs.provider_licensure import LICENSURE_ENTITY
from src.framework.dispatch.registry import register_entity
from src.framework.dispatch.resource_routes import mount_entity

router = register_entity(PROVIDER_ENTITY)


# Every verb auto-binds: `create` reads `PROVIDER_ENTITY.children` to
# append inline credential rows; `list` echoes filter selections; the
# create form picks up `schema=ProviderCreate` from `spec.create_adapter`
# via `make_new_form_handler`. Per-viewer detail extras
# (`provider_detail_extras` + the user-favorite repo it needs) live on
# the spec via dotted-path late-binding. Owned credential subentities
# (licensure, education, certification) self-register on
# `PROVIDER_ENTITY.children` and pick up the same auto-bind for their
# create / update / delete factories.
mount_entity(
    router,
    PROVIDER_ENTITY,
    owned_subentities=(LICENSURE_ENTITY, EDUCATION_ENTITY, CERTIFICATION_ENTITY),
)
