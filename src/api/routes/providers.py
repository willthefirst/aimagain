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
# Registered before `/{provider_id}` so the literal `form` is not parsed as a UUID.


@router.get("/form")
async def get_provider_form(
    request: Request,
    user: User = Depends(current_active_user),
):
    """Renders the create-profile HTML form."""
    context = await handle_get_provider_form(request=request, requesting_user=user)
    return APIResponse.html_response(
        template_name="providers/new.html",
        context=context,
        request=request,
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


@router.get("/{provider_id}/form")
async def get_provider_edit_form(
    provider_id: UUID,
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    user: User = Depends(current_active_user),
):
    """Renders the edit-profile HTML page. Owner-only; admins may edit any
    profile. 404 if missing, 403 if not authorized.
    """
    context = await handle_get_provider_edit_form(
        request=request,
        provider_id=provider_id,
        repo=repo,
        requesting_user=user,
    )
    return APIResponse.html_response(
        template_name="providers/edit.html",
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


# --- Licensure sub-resource ---------------------------------------------


@router.post("/{provider_id}/licensures", status_code=status.HTTP_201_CREATED)
async def create_licensure(
    provider_id: UUID,
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    payload = await parse_and_validate_form(request, licensure_create_adapter)
    created = await handle_create_licensure(
        provider_id=provider_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return created_response(
        id=created.id,
        location=f"/providers/{provider_id}",
        hx_redirect=f"/providers/{provider_id}/form",
    )


@router.patch("/{provider_id}/licensures/{licensure_id}")
async def patch_licensure(
    provider_id: UUID,
    licensure_id: UUID,
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    payload = await parse_and_validate_form(request, licensure_update_adapter)
    updated = await handle_update_licensure(
        provider_id=provider_id,
        licensure_id=licensure_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return updated_response(
        body=_licensure_read_dict(updated),
        hx_redirect=f"/providers/{provider_id}/form",
    )


@router.delete(
    "/{provider_id}/licensures/{licensure_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_licensure(
    provider_id: UUID,
    licensure_id: UUID,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    await handle_delete_licensure(
        provider_id=provider_id,
        licensure_id=licensure_id,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return deleted_response(hx_redirect=f"/providers/{provider_id}/form")


# --- Education sub-resource ---------------------------------------------


@router.post("/{provider_id}/educations", status_code=status.HTTP_201_CREATED)
async def create_education(
    provider_id: UUID,
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    payload = await parse_and_validate_form(request, education_create_adapter)
    created = await handle_create_education(
        provider_id=provider_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return created_response(
        id=created.id,
        location=f"/providers/{provider_id}",
        hx_redirect=f"/providers/{provider_id}/form",
    )


@router.patch("/{provider_id}/educations/{education_id}")
async def patch_education(
    provider_id: UUID,
    education_id: UUID,
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    payload = await parse_and_validate_form(request, education_update_adapter)
    updated = await handle_update_education(
        provider_id=provider_id,
        education_id=education_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return updated_response(
        body=_education_read_dict(updated),
        hx_redirect=f"/providers/{provider_id}/form",
    )


@router.delete(
    "/{provider_id}/educations/{education_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_education(
    provider_id: UUID,
    education_id: UUID,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    await handle_delete_education(
        provider_id=provider_id,
        education_id=education_id,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return deleted_response(hx_redirect=f"/providers/{provider_id}/form")


# --- Certification sub-resource -----------------------------------------


@router.post("/{provider_id}/certifications", status_code=status.HTTP_201_CREATED)
async def create_certification(
    provider_id: UUID,
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    payload = await parse_and_validate_form(request, certification_create_adapter)
    created = await handle_create_certification(
        provider_id=provider_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return created_response(
        id=created.id,
        location=f"/providers/{provider_id}",
        hx_redirect=f"/providers/{provider_id}/form",
    )


@router.patch("/{provider_id}/certifications/{certification_id}")
async def patch_certification(
    provider_id: UUID,
    certification_id: UUID,
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    payload = await parse_and_validate_form(request, certification_update_adapter)
    updated = await handle_update_certification(
        provider_id=provider_id,
        certification_id=certification_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return updated_response(
        body=_certification_read_dict(updated),
        hx_redirect=f"/providers/{provider_id}/form",
    )


@router.delete(
    "/{provider_id}/certifications/{certification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_certification(
    provider_id: UUID,
    certification_id: UUID,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    await handle_delete_certification(
        provider_id=provider_id,
        certification_id=certification_id,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return deleted_response(hx_redirect=f"/providers/{provider_id}/form")
