import logging

from fastapi import APIRouter

from src.api.common import BaseRouter
from src.api.common.resource_routes import (
    QueryParam,
    ResourceSpec,
    mount_create,
    mount_delete,
    mount_detail,
    mount_form,
    mount_list,
    mount_update,
)
from src.auth_config import current_active_user
from src.logic._authz import assert_owner_or_admin
from src.logic.providers.provider_processing import (
    CERTIFICATION,
    EDUCATION,
    LICENSURE,
    handle_create_certification,
    handle_create_education,
    handle_create_licensure,
    handle_create_provider,
    handle_delete_certification,
    handle_delete_education,
    handle_delete_licensure,
    handle_delete_provider,
    handle_get_provider_detail,
    handle_get_provider_edit_form,
    handle_get_provider_form,
    handle_list_providers,
    handle_update_certification,
    handle_update_education,
    handle_update_licensure,
    handle_update_provider,
)
from src.repositories.dependencies import get_audit_repository, get_provider_repository
from src.schemas.providers.provider import (
    ProviderCertificationRead,
    ProviderEducationRead,
    ProviderLicensureRead,
    ProviderRead,
    certification_create_adapter,
    certification_update_adapter,
    education_create_adapter,
    education_update_adapter,
    licensure_create_adapter,
    licensure_update_adapter,
    provider_create_adapter,
    provider_update_adapter,
)

providers_api_router = APIRouter(prefix="/providers")
router = BaseRouter(router=providers_api_router, default_tags=["providers"])
logger = logging.getLogger(__name__)


PROVIDER_SPEC = ResourceSpec(
    collection="providers",
    id_param="provider_id",
    repo_dep=get_provider_repository,
    read_user_dep=current_active_user,
    write_user_dep=current_active_user,
    write_authz=assert_owner_or_admin,
    create_adapter=provider_create_adapter,
    update_adapter=provider_update_adapter,
    read_to_dict=lambda profile: ProviderRead.model_validate(profile).model_dump(
        mode="json"
    ),
    list_template="providers/list.html",
    detail_template="providers/detail.html",
    # After create, redirect to the edit form so the user can flesh out
    # sub-rows (licensures, educations, certifications). After update,
    # send them back to the same edit form.
    create_redirect=lambda *, provider_id: f"/providers/{provider_id}/form",
    update_redirect=lambda *, provider_id: f"/providers/{provider_id}/form",
)


def _licensure_read_dict(row) -> dict:
    return ProviderLicensureRead.model_validate(row).model_dump(mode="json")


def _education_read_dict(row) -> dict:
    return ProviderEducationRead.model_validate(row).model_dump(mode="json")


def _certification_read_dict(row) -> dict:
    return ProviderCertificationRead.model_validate(row).model_dump(mode="json")


# --- Profile collection routes ------------------------------------------

# GET /providers — authenticated listing with optional license_type /
# issuing_state filters.
mount_list(
    router,
    PROVIDER_SPEC,
    handler=handle_list_providers,
    query_params=(
        QueryParam("license_type", str | None, None),
        QueryParam("issuing_state", str | None, None),
    ),
)

# POST /providers — owner inferred from session.
mount_create(
    router,
    PROVIDER_SPEC,
    handler=handle_create_provider,
    audit_repo_dep=get_audit_repository,
)


# --- Form routes --------------------------------------------------------
# Mounted before `/{provider_id}` so the literal `form` segment is not
# parsed as a UUID. Two form templates: `new.html` (create) and
# `edit.html` (edit, identifies the profile from the URL id).
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


# --- Profile item routes ------------------------------------------------

# GET /providers/{provider_id} — detail page.
mount_detail(router, PROVIDER_SPEC, handler=handle_get_provider_detail)


# PATCH /providers/{provider_id} — partial update, owner-or-admin (handler enforces).
mount_update(
    router,
    PROVIDER_SPEC,
    handler=handle_update_provider,
    audit_repo_dep=get_audit_repository,
)
# DELETE /providers/{provider_id} — hard delete, sub-rows cascade.
mount_delete(
    router,
    PROVIDER_SPEC,
    handler=handle_delete_provider,
    audit_repo_dep=get_audit_repository,
)


# --- Sub-resource CRUD (licensure / education / certification) ----------
# Each sub-resource is a `ResourceSpec` whose `parent=PROVIDER_SPEC`.
# The mount functions walk the parent chain to build paths like
# `/{provider_id}/licensures/{licensure_id}` and inject parent ids into
# the handler under their declared kwarg names.


def _provider_subresource_redirect(*, provider_id, **_):
    """Sub-row mutations redirect HTMX clients back to the provider edit
    form so the user can keep editing the parent + its credentials."""
    return f"/providers/{provider_id}/form"


LICENSURE_SPEC = ResourceSpec(
    collection="licensures",
    id_param="licensure_id",
    repo_dep=get_provider_repository,
    audit_resource=LICENSURE,
    write_user_dep=current_active_user,
    write_authz=assert_owner_or_admin,
    create_adapter=licensure_create_adapter,
    update_adapter=licensure_update_adapter,
    read_to_dict=_licensure_read_dict,
    create_redirect=_provider_subresource_redirect,
    update_redirect=_provider_subresource_redirect,
    delete_redirect=_provider_subresource_redirect,
    parent=PROVIDER_SPEC,
)
EDUCATION_SPEC = ResourceSpec(
    collection="educations",
    id_param="education_id",
    repo_dep=get_provider_repository,
    audit_resource=EDUCATION,
    write_user_dep=current_active_user,
    write_authz=assert_owner_or_admin,
    create_adapter=education_create_adapter,
    update_adapter=education_update_adapter,
    read_to_dict=_education_read_dict,
    create_redirect=_provider_subresource_redirect,
    update_redirect=_provider_subresource_redirect,
    delete_redirect=_provider_subresource_redirect,
    parent=PROVIDER_SPEC,
)
CERTIFICATION_SPEC = ResourceSpec(
    collection="certifications",
    id_param="certification_id",
    repo_dep=get_provider_repository,
    audit_resource=CERTIFICATION,
    write_user_dep=current_active_user,
    write_authz=assert_owner_or_admin,
    create_adapter=certification_create_adapter,
    update_adapter=certification_update_adapter,
    read_to_dict=_certification_read_dict,
    create_redirect=_provider_subresource_redirect,
    update_redirect=_provider_subresource_redirect,
    delete_redirect=_provider_subresource_redirect,
    parent=PROVIDER_SPEC,
)


for _spec, _create, _update, _delete in (
    (
        LICENSURE_SPEC,
        handle_create_licensure,
        handle_update_licensure,
        handle_delete_licensure,
    ),
    (
        EDUCATION_SPEC,
        handle_create_education,
        handle_update_education,
        handle_delete_education,
    ),
    (
        CERTIFICATION_SPEC,
        handle_create_certification,
        handle_update_certification,
        handle_delete_certification,
    ),
):
    mount_create(router, _spec, handler=_create, audit_repo_dep=get_audit_repository)
    mount_update(router, _spec, handler=_update, audit_repo_dep=get_audit_repository)
    mount_delete(router, _spec, handler=_delete, audit_repo_dep=get_audit_repository)
