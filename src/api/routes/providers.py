import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter

from src.api.common import (
    APIResponse,
    BaseRouter,
    parse_form_to_payload,
    validate_or_422,
)
from src.auth_config import current_active_user
from src.logic.provider_processing import (
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
from src.repositories.provider_repository import ProviderRepository
from src.schemas.provider import (
    ProviderCertificationCreate,
    ProviderCertificationRead,
    ProviderCertificationUpdate,
    ProviderCreate,
    ProviderEducationCreate,
    ProviderEducationRead,
    ProviderEducationUpdate,
    ProviderLicensureCreate,
    ProviderLicensureRead,
    ProviderLicensureUpdate,
    ProviderRead,
    ProviderUpdate,
)

providers_api_router = APIRouter(prefix="/providers")
router = BaseRouter(router=providers_api_router, default_tags=["providers"])
logger = logging.getLogger(__name__)


# Module-level TypeAdapters mirror the `post_create_adapter` / `post_update_adapter`
# pattern in `src/schemas/post.py` — pre-built adapters keep validation in one place
# per schema. Defined here (not in the schema module) because the provider-profile
# schemas don't currently expose discriminated unions that would need an adapter
# anywhere else.
_provider_create_adapter: TypeAdapter = TypeAdapter(ProviderCreate)
_provider_update_adapter: TypeAdapter = TypeAdapter(ProviderUpdate)
_licensure_create_adapter: TypeAdapter = TypeAdapter(ProviderLicensureCreate)
_licensure_update_adapter: TypeAdapter = TypeAdapter(ProviderLicensureUpdate)
_education_create_adapter: TypeAdapter = TypeAdapter(ProviderEducationCreate)
_education_update_adapter: TypeAdapter = TypeAdapter(ProviderEducationUpdate)
_certification_create_adapter: TypeAdapter = TypeAdapter(ProviderCertificationCreate)
_certification_update_adapter: TypeAdapter = TypeAdapter(ProviderCertificationUpdate)


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
    """Public HTML listing of provider profiles. Optional `license_type` and
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
    """Creates a provider profile owned by the requesting user. Form-encoded
    body. A user may own multiple profiles."""
    payload_dict = await parse_form_to_payload(request)
    payload = validate_or_422(_provider_create_adapter, payload_dict)
    created = await handle_create_provider(
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    detail_location = f"/providers/{created.id}"
    edit_location = f"/providers/{created.id}/form"
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"id": str(created.id)},
        headers={"Location": detail_location, "HX-Redirect": edit_location},
    )


# --- Form routes --------------------------------------------------------
# Registered before `/{profile_id}` so the literal `form` is not parsed as a UUID.


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


@router.get("/{profile_id}")
async def get_profile(
    profile_id: UUID,
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    user: User = Depends(current_active_user),
):
    """Renders an HTML detail page for any profile. 404 if missing."""
    context = await handle_get_provider_detail(
        request=request,
        profile_id=profile_id,
        repo=repo,
        requesting_user=user,
    )
    return APIResponse.html_response(
        template_name="providers/detail.html",
        context=context,
        request=request,
    )


@router.get("/{profile_id}/form")
async def get_provider_edit_form(
    profile_id: UUID,
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    user: User = Depends(current_active_user),
):
    """Renders the edit-profile HTML page. Owner-only; admins may edit any
    profile. 404 if missing, 403 if not authorized.
    """
    context = await handle_get_provider_edit_form(
        request=request,
        profile_id=profile_id,
        repo=repo,
        requesting_user=user,
    )
    return APIResponse.html_response(
        template_name="providers/edit.html",
        context=context,
        request=request,
    )


@router.patch("/{profile_id}")
async def patch_profile(
    profile_id: UUID,
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    """Partially updates the practice/availability fields. Owner-only; admins
    may edit any profile. Sub-entity lists are managed via their own routes."""
    payload_dict = await parse_form_to_payload(request)
    payload = validate_or_422(_provider_update_adapter, payload_dict)
    updated = await handle_update_provider(
        profile_id=profile_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    location = f"/providers/{updated.id}/form"
    return JSONResponse(
        content=_provider_read_dict(updated),
        headers={"HX-Redirect": location},
    )


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    profile_id: UUID,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    """Hard-deletes the profile (sub-rows cascade). Owner-only; admins may
    delete any profile."""
    await handle_delete_provider(
        profile_id=profile_id,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"HX-Redirect": "/providers"},
    )


# --- Licensure sub-resource ---------------------------------------------


@router.post("/{profile_id}/licensures", status_code=status.HTTP_201_CREATED)
async def create_licensure(
    profile_id: UUID,
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    payload_dict = await parse_form_to_payload(request)
    payload = validate_or_422(_licensure_create_adapter, payload_dict)
    created = await handle_create_licensure(
        profile_id=profile_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    parent_location = f"/providers/{profile_id}"
    edit_location = f"/providers/{profile_id}/form"
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"id": str(created.id)},
        headers={"Location": parent_location, "HX-Redirect": edit_location},
    )


@router.patch("/{profile_id}/licensures/{licensure_id}")
async def patch_licensure(
    profile_id: UUID,
    licensure_id: UUID,
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    payload_dict = await parse_form_to_payload(request)
    payload = validate_or_422(_licensure_update_adapter, payload_dict)
    updated = await handle_update_licensure(
        profile_id=profile_id,
        licensure_id=licensure_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    location = f"/providers/{profile_id}/form"
    return JSONResponse(
        content=_licensure_read_dict(updated),
        headers={"HX-Redirect": location},
    )


@router.delete(
    "/{profile_id}/licensures/{licensure_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_licensure(
    profile_id: UUID,
    licensure_id: UUID,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    await handle_delete_licensure(
        profile_id=profile_id,
        licensure_id=licensure_id,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"HX-Redirect": f"/providers/{profile_id}/form"},
    )


# --- Education sub-resource ---------------------------------------------


@router.post("/{profile_id}/educations", status_code=status.HTTP_201_CREATED)
async def create_education(
    profile_id: UUID,
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    payload_dict = await parse_form_to_payload(request)
    payload = validate_or_422(_education_create_adapter, payload_dict)
    created = await handle_create_education(
        profile_id=profile_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    parent_location = f"/providers/{profile_id}"
    edit_location = f"/providers/{profile_id}/form"
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"id": str(created.id)},
        headers={"Location": parent_location, "HX-Redirect": edit_location},
    )


@router.patch("/{profile_id}/educations/{education_id}")
async def patch_education(
    profile_id: UUID,
    education_id: UUID,
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    payload_dict = await parse_form_to_payload(request)
    payload = validate_or_422(_education_update_adapter, payload_dict)
    updated = await handle_update_education(
        profile_id=profile_id,
        education_id=education_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    location = f"/providers/{profile_id}/form"
    return JSONResponse(
        content=_education_read_dict(updated),
        headers={"HX-Redirect": location},
    )


@router.delete(
    "/{profile_id}/educations/{education_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_education(
    profile_id: UUID,
    education_id: UUID,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    await handle_delete_education(
        profile_id=profile_id,
        education_id=education_id,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"HX-Redirect": f"/providers/{profile_id}/form"},
    )


# --- Certification sub-resource -----------------------------------------


@router.post("/{profile_id}/certifications", status_code=status.HTTP_201_CREATED)
async def create_certification(
    profile_id: UUID,
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    payload_dict = await parse_form_to_payload(request)
    payload = validate_or_422(_certification_create_adapter, payload_dict)
    created = await handle_create_certification(
        profile_id=profile_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    parent_location = f"/providers/{profile_id}"
    edit_location = f"/providers/{profile_id}/form"
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"id": str(created.id)},
        headers={"Location": parent_location, "HX-Redirect": edit_location},
    )


@router.patch("/{profile_id}/certifications/{certification_id}")
async def patch_certification(
    profile_id: UUID,
    certification_id: UUID,
    request: Request,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    payload_dict = await parse_form_to_payload(request)
    payload = validate_or_422(_certification_update_adapter, payload_dict)
    updated = await handle_update_certification(
        profile_id=profile_id,
        certification_id=certification_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    location = f"/providers/{profile_id}/form"
    return JSONResponse(
        content=_certification_read_dict(updated),
        headers={"HX-Redirect": location},
    )


@router.delete(
    "/{profile_id}/certifications/{certification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_certification(
    profile_id: UUID,
    certification_id: UUID,
    repo: ProviderRepository = Depends(get_provider_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    await handle_delete_certification(
        profile_id=profile_id,
        certification_id=certification_id,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"HX-Redirect": f"/providers/{profile_id}/form"},
    )
