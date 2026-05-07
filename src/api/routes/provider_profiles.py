import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError

from src.api.common import BaseRouter
from src.api.routes.posts import parse_form_to_payload
from src.auth_config import current_active_user
from src.logic.provider_profile_processing import (
    handle_create_certification,
    handle_create_education,
    handle_create_licensure,
    handle_create_profile,
    handle_delete_certification,
    handle_delete_education,
    handle_delete_licensure,
    handle_delete_profile,
    handle_get_my_profile,
    handle_get_profile,
    handle_list_profiles,
    handle_update_certification,
    handle_update_education,
    handle_update_licensure,
    handle_update_profile,
)
from src.models import User
from src.repositories.audit_repository import AuditRepository
from src.repositories.dependencies import (
    get_audit_repository,
    get_provider_profile_repository,
)
from src.repositories.provider_profile_repository import ProviderProfileRepository
from src.schemas.provider_profile import (
    ProviderCertificationCreate,
    ProviderCertificationRead,
    ProviderCertificationUpdate,
    ProviderEducationCreate,
    ProviderEducationRead,
    ProviderEducationUpdate,
    ProviderLicensureCreate,
    ProviderLicensureRead,
    ProviderLicensureUpdate,
    ProviderProfileCreate,
    ProviderProfileRead,
    ProviderProfileUpdate,
)

provider_profiles_api_router = APIRouter(prefix="/provider-profiles")
router = BaseRouter(
    router=provider_profiles_api_router, default_tags=["provider-profiles"]
)
logger = logging.getLogger(__name__)


# Module-level TypeAdapters mirror the `post_create_adapter` / `post_update_adapter`
# pattern in `src/schemas/post.py` — pre-built adapters keep validation in one place
# per schema. Defined here (not in the schema module) because the provider-profile
# schemas don't currently expose discriminated unions that would need an adapter
# anywhere else.
_profile_create_adapter: TypeAdapter = TypeAdapter(ProviderProfileCreate)
_profile_update_adapter: TypeAdapter = TypeAdapter(ProviderProfileUpdate)
_licensure_create_adapter: TypeAdapter = TypeAdapter(ProviderLicensureCreate)
_licensure_update_adapter: TypeAdapter = TypeAdapter(ProviderLicensureUpdate)
_education_create_adapter: TypeAdapter = TypeAdapter(ProviderEducationCreate)
_education_update_adapter: TypeAdapter = TypeAdapter(ProviderEducationUpdate)
_certification_create_adapter: TypeAdapter = TypeAdapter(ProviderCertificationCreate)
_certification_update_adapter: TypeAdapter = TypeAdapter(ProviderCertificationUpdate)


def _validate_or_422(adapter: TypeAdapter, payload_dict: dict):
    """Run a payload dict through a `TypeAdapter` and translate `ValidationError`
    to the wire-shape 422 used by `src/api/routes/posts.py:155-167`."""
    try:
        return adapter.validate_python(payload_dict)
    except ValidationError as e:
        errors = [
            {"loc": err["loc"], "msg": err["msg"], "type": err["type"]}
            for err in e.errors()
        ]
        raise HTTPException(status_code=422, detail=errors)


def _profile_read_dict(profile) -> dict:
    return ProviderProfileRead.model_validate(profile).model_dump(mode="json")


def _licensure_read_dict(row) -> dict:
    return ProviderLicensureRead.model_validate(row).model_dump(mode="json")


def _education_read_dict(row) -> dict:
    return ProviderEducationRead.model_validate(row).model_dump(mode="json")


def _certification_read_dict(row) -> dict:
    return ProviderCertificationRead.model_validate(row).model_dump(mode="json")


# --- Profile collection routes ------------------------------------------


@router.get("")
async def list_profiles(
    license_type: str | None = Query(None),
    issuing_state: str | None = Query(None),
    repo: ProviderProfileRepository = Depends(get_provider_profile_repository),
):
    """Public listing of provider profiles. Optional `license_type` and
    `issuing_state` filters narrow the results to profiles that hold a
    licensure matching both filters."""
    profiles = await handle_list_profiles(
        repo, license_type=license_type, issuing_state=issuing_state
    )
    return JSONResponse(content=[_profile_read_dict(p) for p in profiles])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_profile(
    request: Request,
    repo: ProviderProfileRepository = Depends(get_provider_profile_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    """Creates the requesting user's provider profile. Form-encoded body. 400 if
    the user already has a profile (one-per-user uniqueness)."""
    payload_dict = await parse_form_to_payload(request)
    payload = _validate_or_422(_profile_create_adapter, payload_dict)
    created = await handle_create_profile(
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    location = f"/provider-profiles/{created.id}"
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"id": str(created.id)},
        headers={"Location": location, "HX-Redirect": location},
    )


# --- Per-actor route ----------------------------------------------------
# Registered before `/{profile_id}` so the literal `me` is not parsed as a UUID.


@router.get("/me")
async def get_my_profile(
    repo: ProviderProfileRepository = Depends(get_provider_profile_repository),
    user: User = Depends(current_active_user),
):
    """Returns the requesting user's profile. 404 if they have not created one
    yet (profiles are not auto-created on registration)."""
    profile = await handle_get_my_profile(repo, user)
    return JSONResponse(content=_profile_read_dict(profile))


# --- Profile item routes ------------------------------------------------


@router.get("/{profile_id}")
async def get_profile(
    profile_id: UUID,
    repo: ProviderProfileRepository = Depends(get_provider_profile_repository),
    user: User = Depends(current_active_user),
):
    """Authenticated read of any profile by id. 404 if missing."""
    profile = await handle_get_profile(profile_id, repo, user)
    return JSONResponse(content=_profile_read_dict(profile))


@router.patch("/{profile_id}")
async def patch_profile(
    profile_id: UUID,
    request: Request,
    repo: ProviderProfileRepository = Depends(get_provider_profile_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    """Partially updates the practice/availability fields. Owner-only; admins
    may edit any profile. Sub-entity lists are managed via their own routes."""
    payload_dict = await parse_form_to_payload(request)
    payload = _validate_or_422(_profile_update_adapter, payload_dict)
    updated = await handle_update_profile(
        profile_id=profile_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    location = f"/provider-profiles/{updated.id}"
    return JSONResponse(
        content=_profile_read_dict(updated),
        headers={"HX-Redirect": location},
    )


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(
    profile_id: UUID,
    repo: ProviderProfileRepository = Depends(get_provider_profile_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    """Hard-deletes the profile (sub-rows cascade). Owner-only; admins may
    delete any profile."""
    await handle_delete_profile(
        profile_id=profile_id,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"HX-Redirect": "/provider-profiles"},
    )


# --- Licensure sub-resource ---------------------------------------------


@router.post("/{profile_id}/licensures", status_code=status.HTTP_201_CREATED)
async def create_licensure(
    profile_id: UUID,
    request: Request,
    repo: ProviderProfileRepository = Depends(get_provider_profile_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    payload_dict = await parse_form_to_payload(request)
    payload = _validate_or_422(_licensure_create_adapter, payload_dict)
    created = await handle_create_licensure(
        profile_id=profile_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    location = f"/provider-profiles/{profile_id}"
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"id": str(created.id)},
        headers={"Location": location, "HX-Redirect": location},
    )


@router.patch("/{profile_id}/licensures/{licensure_id}")
async def patch_licensure(
    profile_id: UUID,
    licensure_id: UUID,
    request: Request,
    repo: ProviderProfileRepository = Depends(get_provider_profile_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    payload_dict = await parse_form_to_payload(request)
    payload = _validate_or_422(_licensure_update_adapter, payload_dict)
    updated = await handle_update_licensure(
        profile_id=profile_id,
        licensure_id=licensure_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    location = f"/provider-profiles/{profile_id}"
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
    repo: ProviderProfileRepository = Depends(get_provider_profile_repository),
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
        headers={"HX-Redirect": f"/provider-profiles/{profile_id}"},
    )


# --- Education sub-resource ---------------------------------------------


@router.post("/{profile_id}/educations", status_code=status.HTTP_201_CREATED)
async def create_education(
    profile_id: UUID,
    request: Request,
    repo: ProviderProfileRepository = Depends(get_provider_profile_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    payload_dict = await parse_form_to_payload(request)
    payload = _validate_or_422(_education_create_adapter, payload_dict)
    created = await handle_create_education(
        profile_id=profile_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    location = f"/provider-profiles/{profile_id}"
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"id": str(created.id)},
        headers={"Location": location, "HX-Redirect": location},
    )


@router.patch("/{profile_id}/educations/{education_id}")
async def patch_education(
    profile_id: UUID,
    education_id: UUID,
    request: Request,
    repo: ProviderProfileRepository = Depends(get_provider_profile_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    payload_dict = await parse_form_to_payload(request)
    payload = _validate_or_422(_education_update_adapter, payload_dict)
    updated = await handle_update_education(
        profile_id=profile_id,
        education_id=education_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    location = f"/provider-profiles/{profile_id}"
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
    repo: ProviderProfileRepository = Depends(get_provider_profile_repository),
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
        headers={"HX-Redirect": f"/provider-profiles/{profile_id}"},
    )


# --- Certification sub-resource -----------------------------------------


@router.post("/{profile_id}/certifications", status_code=status.HTTP_201_CREATED)
async def create_certification(
    profile_id: UUID,
    request: Request,
    repo: ProviderProfileRepository = Depends(get_provider_profile_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    payload_dict = await parse_form_to_payload(request)
    payload = _validate_or_422(_certification_create_adapter, payload_dict)
    created = await handle_create_certification(
        profile_id=profile_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    location = f"/provider-profiles/{profile_id}"
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"id": str(created.id)},
        headers={"Location": location, "HX-Redirect": location},
    )


@router.patch("/{profile_id}/certifications/{certification_id}")
async def patch_certification(
    profile_id: UUID,
    certification_id: UUID,
    request: Request,
    repo: ProviderProfileRepository = Depends(get_provider_profile_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    user: User = Depends(current_active_user),
):
    payload_dict = await parse_form_to_payload(request)
    payload = _validate_or_422(_certification_update_adapter, payload_dict)
    updated = await handle_update_certification(
        profile_id=profile_id,
        certification_id=certification_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=user,
    )
    location = f"/provider-profiles/{profile_id}"
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
    repo: ProviderProfileRepository = Depends(get_provider_profile_repository),
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
        headers={"HX-Redirect": f"/provider-profiles/{profile_id}"},
    )
