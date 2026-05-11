import logging

from fastapi import APIRouter

from src.api.common import BaseRouter
from src.api.common.resource_routes import mount_entity
from src.api.common.specs.provider import PROVIDER_ENTITY
from src.api.common.specs.provider_certification import CERTIFICATION_ENTITY
from src.api.common.specs.provider_education import EDUCATION_ENTITY
from src.api.common.specs.provider_licensure import LICENSURE_ENTITY
from src.logic._generic import (
    make_create_handler,
    make_delete_handler,
    make_update_handler,
)
from src.logic.providers.provider_processing import (
    handle_create_provider,
    handle_get_provider_detail,
    handle_get_provider_edit_form,
    handle_get_provider_form,
    handle_list_providers,
)

providers_api_router = APIRouter(prefix="/providers")
router = BaseRouter(router=providers_api_router, default_tags=["providers"])
logger = logging.getLogger(__name__)


# Named module-level attributes for framework-built handlers so
# contract-test patches (e.g. `src.api.routes.providers._handle_update_provider`)
# flow through the mount layer's `_resolve_handler`. The `__module__`
# is rebound so `_resolve_handler` looks up against this module.
def _named(handler, name):
    handler.__name__ = name
    handler.__qualname__ = name
    handler.__module__ = __name__
    return handler


_handle_update_provider = _named(
    make_update_handler(PROVIDER_ENTITY), "_handle_update_provider"
)
_handle_delete_provider = _named(
    make_delete_handler(PROVIDER_ENTITY), "_handle_delete_provider"
)


mount_entity(
    router,
    PROVIDER_ENTITY,
    handlers={
        "list": handle_list_providers,
        "detail": handle_get_provider_detail,
        # Bespoke create (inline credentials append); other verbs are
        # generic factory-built.
        "create": handle_create_provider,
        "update": _handle_update_provider,
        "delete": _handle_delete_provider,
        "form_new": handle_get_provider_form,
        "form_edit": handle_get_provider_edit_form,
        # Owned-subentity verbs, keyed by `<owned.name>.<verb>`.
        "provider_licensure.create": make_create_handler(LICENSURE_ENTITY),
        "provider_licensure.update": make_update_handler(LICENSURE_ENTITY),
        "provider_licensure.delete": make_delete_handler(LICENSURE_ENTITY),
        "provider_education.create": make_create_handler(EDUCATION_ENTITY),
        "provider_education.update": make_update_handler(EDUCATION_ENTITY),
        "provider_education.delete": make_delete_handler(EDUCATION_ENTITY),
        "provider_certification.create": make_create_handler(CERTIFICATION_ENTITY),
        "provider_certification.update": make_update_handler(CERTIFICATION_ENTITY),
        "provider_certification.delete": make_delete_handler(CERTIFICATION_ENTITY),
    },
    owned_subentities=(LICENSURE_ENTITY, EDUCATION_ENTITY, CERTIFICATION_ENTITY),
)
