import logging

from fastapi import APIRouter

from src.api.common import BaseRouter
from src.api.common.resource_routes import (
    mount_create,
    mount_delete,
    mount_detail,
    mount_form,
    mount_list,
    mount_update,
)
from src.api.common.specs.provider import PROVIDER_ENTITY
from src.api.common.specs.provider_certification import CERTIFICATION_ENTITY
from src.api.common.specs.provider_education import EDUCATION_ENTITY
from src.api.common.specs.provider_licensure import LICENSURE_ENTITY
from src.logic._generic import make_create_handler, make_delete_handler
from src.logic.providers.provider_processing import (
    handle_create_provider,
    handle_get_provider_detail,
    handle_get_provider_edit_form,
    handle_get_provider_form,
    handle_list_providers,
    handle_update_certification,
    handle_update_education,
    handle_update_licensure,
    handle_update_provider,
)

providers_api_router = APIRouter(prefix="/providers")
router = BaseRouter(router=providers_api_router, default_tags=["providers"])
logger = logging.getLogger(__name__)


# All four route-level ResourceSpecs are derived from their EntitySpecs.
# The entity specs in `src/api/common/specs/` are the single declaration
# of identity (audit binding, adapters, redirects, filters, route flags,
# templates); the mount helpers still consume `ResourceSpec`, so we
# bridge via `to_resource_spec()`.
PROVIDER_SPEC = PROVIDER_ENTITY.to_resource_spec()
LICENSURE_SPEC = LICENSURE_ENTITY.to_resource_spec()
EDUCATION_SPEC = EDUCATION_ENTITY.to_resource_spec()
CERTIFICATION_SPEC = CERTIFICATION_ENTITY.to_resource_spec()


# --- Provider collection routes ------------------------------------------

# GET /providers — authenticated listing with optional license_type /
# issuing_state filters. The filter shape is declared on the entity spec
# so the canonical declaration lives upstream of the mount call.
mount_list(
    router,
    PROVIDER_SPEC,
    handler=handle_list_providers,
    query_params=PROVIDER_ENTITY.filters,
)

# POST /providers — owner inferred from session.
mount_create(router, PROVIDER_SPEC, handler=handle_create_provider)


# --- Form routes --------------------------------------------------------
# Mounted before `/{provider_id}` so the literal `form` segment is not
# parsed as a UUID. Two form templates: `new.html` (create) and
# `edit.html` (edit, identifies the provider from the URL id).
mount_form(
    router,
    PROVIDER_SPEC,
    handler=handle_get_provider_form,
    template="providers/new.html",
)
mount_form(
    router,
    PROVIDER_SPEC,
    handler=handle_get_provider_edit_form,
    template="providers/edit.html",
    on_existing=True,
)


# --- Provider item routes ------------------------------------------------

# GET /providers/{provider_id} — detail page. The `is_favorited` per-viewer
# flag (computed in the handler against `UserFavoriteRepository`) lives in
# the template context; the handler's typed signature is enough — the
# mount's signature synthesis resolves the favorites repo via the type
# registry, no explicit wiring needed.
mount_detail(router, PROVIDER_SPEC, handler=handle_get_provider_detail)


# PATCH /providers/{provider_id} — partial update, owner-or-admin (handler enforces).
mount_update(router, PROVIDER_SPEC, handler=handle_update_provider)
# DELETE /providers/{provider_id} — hard delete, sub-rows cascade.
# Generic delete: `make_delete_handler` builds a callable from the entity
# spec (audit binding + write_authz). See `src/logic/_generic.py`.
mount_delete(router, PROVIDER_SPEC, handler=make_delete_handler(PROVIDER_ENTITY))


# --- Sub-resource CRUD (licensure / education / certification) ----------
# Each sub-resource's spec carries `parent=PROVIDER_ENTITY` (resolved on
# the entity spec), so `to_resource_spec()` produces a `ResourceSpec`
# whose `parent` is a derived `PROVIDER_SPEC`. The mount functions walk
# that parent chain to build paths like
# `/{provider_id}/licensures/{licensure_id}` and inject parent ids into
# the handler under their declared kwarg names.


for _spec, _entity, _update in (
    (LICENSURE_SPEC, LICENSURE_ENTITY, handle_update_licensure),
    (EDUCATION_SPEC, EDUCATION_ENTITY, handle_update_education),
    (CERTIFICATION_SPEC, CERTIFICATION_ENTITY, handle_update_certification),
):
    mount_create(router, _spec, handler=make_create_handler(_entity))
    mount_update(router, _spec, handler=_update)
    mount_delete(router, _spec, handler=make_delete_handler(_entity))
