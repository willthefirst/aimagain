import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from src.api.common import (
    APIResponse,
    BaseRouter,
    created_response,
    deleted_response,
    parse_and_validate_form,
    updated_response,
)
from src.api.common.resource_routes import ResourceSpec, mount_form
from src.api.common.subresource_routes import (
    SubresourceDeps,
    SubresourceSpec,
    register_subresource_routes,
)
from src.auth_config import current_active_user
from src.logic.providers.provider_processing import (
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
from src.models import User
from src.repositories.audit_repository import AuditRepository
from src.repositories.dependencies import get_audit_repository, get_provider_repository
from src.repositories.providers.provider_repository import ProviderRepository
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


# Spec is incrementally fleshed out as each slice migrates more operations
# onto the mounts. Slice 5 (#250) fills in just enough to mount the two
# form routes; slice 6 (#251) adds adapters/redirects for create/update.
PROVIDER_SPEC = ResourceSpec(
    collection="providers",
    id_param="provider_id",
    repo_dep=get_provider_repository,
    read_user_dep=current_active_user,
    write_user_dep=current_active_user,
)


def _provider_read_dict(profile) -> dict:
    return ProviderRead.model_validate(profile).model_dump(mode="json")


def _licensure_read_dict(row) -> dict:
    return ProviderLicensureRead.model_validate(row).model_dump(mode="json")


def _education_read_dict(row) -> dict:
    return ProviderEducationRead.model_validate(row).model_dump(mode="json")


def _certification_read_dict(row) -> dict:
    return ProviderCertificationRead.model_validate(row).model_dump(mode="json")


# --- Profile collection routes ------------------------------------------


@router.get("")
async def list_providers(
    request: Request,
    license_type: str | None = Query(None),
    issuing_state: str | None = Query(None),
    repo: ProviderRepository = Depends(get_provider_repository),
):
    """Public HTML listing of providers. Optional `license_type` and
    `issuing_state` filters narrow the results to profiles that hold a
    licensure matching both filters."""
    context = await handle_list_providers(
        request=request,
        repo=repo,
        license_type=license_type,
        issuing_state=issuing_state,
    )
    return APIResponse.html_response(
        template_name="providers/list.html",
        context=context,
        request=request,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_provider(
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    """Creates a provider owned by the requesting user. Form-encoded
    body. A user may own multiple profiles."""
    payload = await parse_and_validate_form(request, provider_create_adapter)
    created = await handle_create_provider(
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return created_response(
        id=created.id,
        location=f"/providers/{created.id}",
        hx_redirect=f"/providers/{created.id}/form",
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


@router.get("/{provider_id}")
async def get_profile(
    provider_id: UUID,
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    user: User = Depends(current_active_user),
):
    """Renders an HTML detail page for any profile. 404 if missing."""
    context = await handle_get_provider_detail(
        request=request,
        provider_id=provider_id,
        repo=repo,
        requesting_user=user,
    )
    return APIResponse.html_response(
        template_name="providers/detail.html",
        context=context,
        request=request,
    )


@router.patch("/{provider_id}")
async def patch_profile(
    provider_id: UUID,
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    """Partially updates the practice/availability fields. Owner-only; admins
    may edit any profile. Sub-entity lists are managed via their own routes."""
    payload = await parse_and_validate_form(request, provider_update_adapter)
    updated = await handle_update_provider(
        provider_id=provider_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return updated_response(
        body=_provider_read_dict(updated),
        hx_redirect=f"/providers/{updated.id}/form",
    )


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: UUID,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    """Hard-deletes the profile (sub-rows cascade). Owner-only; admins may
    delete any profile."""
    await handle_delete_provider(
        provider_id=provider_id,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return deleted_response(hx_redirect="/providers")


# --- Sub-resource CRUD (licensure / education / certification) ----------
# Three near-identical CRUD blocks live in src/api/common/subresource_routes.py
# and are mounted via register_subresource_routes; per-sub-resource knobs
# (path segment, schemas, handlers, child-id kwarg name) live in the specs
# below.

_provider_subresource_deps = SubresourceDeps(
    repo=get_provider_repository,
    audit_repo=get_audit_repository,
    user=current_active_user,
)

register_subresource_routes(
    router,
    SubresourceSpec(
        collection="licensures",
        child_id_param="licensure_id",
        create_adapter=licensure_create_adapter,
        update_adapter=licensure_update_adapter,
        read_to_dict=_licensure_read_dict,
        create_handler=handle_create_licensure,
        update_handler=handle_update_licensure,
        delete_handler=handle_delete_licensure,
    ),
    deps=_provider_subresource_deps,
)

register_subresource_routes(
    router,
    SubresourceSpec(
        collection="educations",
        child_id_param="education_id",
        create_adapter=education_create_adapter,
        update_adapter=education_update_adapter,
        read_to_dict=_education_read_dict,
        create_handler=handle_create_education,
        update_handler=handle_update_education,
        delete_handler=handle_delete_education,
    ),
    deps=_provider_subresource_deps,
)

register_subresource_routes(
    router,
    SubresourceSpec(
        collection="certifications",
        child_id_param="certification_id",
        create_adapter=certification_create_adapter,
        update_adapter=certification_update_adapter,
        read_to_dict=_certification_read_dict,
        create_handler=handle_create_certification,
        update_handler=handle_update_certification,
        delete_handler=handle_delete_certification,
    ),
    deps=_provider_subresource_deps,
)
