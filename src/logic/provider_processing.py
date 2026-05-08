"""Provider-profile orchestration handlers.

One file per resource family — the parent profile plus its three credential
sub-tables (licensure, education, certification). Each mutation handler
owns the transaction commit and writes a single audit row covering the
mutation, per `RESOURCE_GRAMMAR.md:135` and the discipline enforced in
`test_audit_discipline.py`.

Authorization is uniform: a provider can mutate only their own profile and
its sub-rows; a superuser can mutate any. Read handlers are open to any
authenticated user.

Sub-resource handlers also assert that the URL's `profile_id` matches the
sub-row's `profile_id`. Without this, `/profiles/A/licensures/B` would
silently mutate a licensure belonging to a different profile.
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel

from src.api.common.exceptions import ForbiddenError, NotFoundError
from src.logic.audit import AuditAction, AuditedResource, mutate
from src.models import (
    Provider,
    ProviderCertification,
    ProviderEducation,
    ProviderLicensure,
    User,
)
from src.repositories.audit_repository import AuditRepository
from src.repositories.provider_repository import ProviderRepository
from src.repositories.user_repository import UserRepository
from src.schemas.provider import (
    ProviderAuditSnapshot,
    ProviderCertificationAuditSnapshot,
    ProviderCertificationCreate,
    ProviderCertificationUpdate,
    ProviderCreate,
    ProviderEducationAuditSnapshot,
    ProviderEducationCreate,
    ProviderEducationUpdate,
    ProviderLicensureAuditSnapshot,
    ProviderLicensureCreate,
    ProviderLicensureUpdate,
    ProviderUpdate,
)

logger = logging.getLogger(__name__)


# --- Audited-resource declarations ---------------------------------------


def _snap(schema_cls: type[BaseModel]):
    """Build a snapshotter that validates an ORM row through the given
    `*AuditSnapshot` schema and returns a JSON-mode dump."""

    def _snapshot(obj: Any) -> dict[str, Any]:
        return schema_cls.model_validate(obj).model_dump(mode="json")

    return _snapshot


PROFILE = AuditedResource(
    type="provider_profile",
    snapshot=_snap(ProviderAuditSnapshot),
    create=AuditAction.CREATE_PROVIDER,
    update=AuditAction.UPDATE_PROVIDER,
    delete=AuditAction.DELETE_PROVIDER,
)
LICENSURE = AuditedResource(
    type="provider_licensure",
    snapshot=_snap(ProviderLicensureAuditSnapshot),
    create=AuditAction.CREATE_LICENSURE,
    update=AuditAction.UPDATE_LICENSURE,
    delete=AuditAction.DELETE_LICENSURE,
)
EDUCATION = AuditedResource(
    type="provider_education",
    snapshot=_snap(ProviderEducationAuditSnapshot),
    create=AuditAction.CREATE_EDUCATION,
    update=AuditAction.UPDATE_EDUCATION,
    delete=AuditAction.DELETE_EDUCATION,
)
CERTIFICATION = AuditedResource(
    type="provider_certification",
    snapshot=_snap(ProviderCertificationAuditSnapshot),
    create=AuditAction.CREATE_CERTIFICATION,
    update=AuditAction.UPDATE_CERTIFICATION,
    delete=AuditAction.DELETE_CERTIFICATION,
)


# --- Authorization helper ------------------------------------------------


def _assert_can_mutate(profile: Provider, user: User) -> None:
    if profile.user_id != user.id and not user.is_superuser:
        raise ForbiddenError(
            detail="Only the profile owner or an admin can perform this action"
        )


async def _load_provider_or_404(profile_id: UUID, repo: ProviderRepository) -> Provider:
    profile = await repo.get_by_id(profile_id)
    if profile is None:
        raise NotFoundError(detail="Provider not found")
    return profile


async def _load_subrow_or_404(getter, sub_id: UUID, parent_id: UUID, *, name: str):
    """Load a credential sub-row and verify its `profile_id` matches the
    URL's `profile_id`. 404 if missing or if the FK is for a different
    parent — without this, `/profiles/A/licensures/B` would silently
    mutate a sub-row owned by profile B."""
    row = await getter(sub_id)
    if row is None or row.profile_id != parent_id:
        raise NotFoundError(detail=f"{name} not found")
    return row


# --- Profile handlers ----------------------------------------------------


async def handle_list_providers(
    request: Request,
    repo: ProviderRepository,
    *,
    license_type: str | None = None,
    issuing_state: str | None = None,
) -> dict[str, Any]:
    """Public listing — no auth gate, no audit, no commit. Returns the
    template context for the HTML list page; the active filter values are
    forwarded so the template can preselect them in its filter form."""
    profiles = await repo.list_providers(
        license_type=license_type, issuing_state=issuing_state
    )
    return {
        "request": request,
        "profiles": profiles,
        "selected_license_type": license_type,
        "selected_issuing_state": issuing_state,
    }


async def handle_get_provider_detail(
    request: Request,
    profile_id: UUID,
    repo: ProviderRepository,
    requesting_user: User,
) -> dict[str, Any]:
    """Loads any profile by id for the read-only detail page; 404 if missing.

    The repo's `get_by_id` eager-loads `licensures`, `educations`, and
    `certifications` via `lazy="selectin"`, so the template can render
    each sub-section without further queries.
    """
    profile = await _load_provider_or_404(profile_id, repo)
    return {"request": request, "profile": profile, "current_user": requesting_user}


async def handle_list_user_providers(
    request: Request,
    target_user_id: UUID,
    repo: ProviderRepository,
    user_repo: UserRepository,
    requesting_user: User,
) -> dict[str, Any]:
    """Returns the template context for the user-scoped provider
    list page. A user may view their own list; admins may view anyone's.
    404 if the target user does not exist; 403 if a non-admin requests
    another user's list.
    """
    if target_user_id != requesting_user.id and not requesting_user.is_superuser:
        raise ForbiddenError(
            detail="Only the target user or an admin may view their providers"
        )
    target_user = await user_repo.get_user_by_id(target_user_id)
    if target_user is None:
        raise NotFoundError(detail=f"User {target_user_id} not found")
    profiles = await repo.list_for_user(target_user_id)
    return {
        "request": request,
        "target_user": target_user,
        "profiles": profiles,
        "is_self": target_user_id == requesting_user.id,
        "current_user": requesting_user,
    }


async def handle_get_provider_form(
    request: Request,
    requesting_user: User,
) -> dict[str, Any]:
    """Builds the template context for the create-provider form."""
    return {"request": request, "current_user": requesting_user}


async def handle_get_provider_edit_form(
    request: Request,
    profile_id: UUID,
    repo: ProviderRepository,
    requesting_user: User,
) -> dict[str, Any]:
    """Loads a profile for the edit-form page. 404 if missing, 403 if the
    requester is neither owner nor admin (mirrors `_assert_can_mutate`).

    The repo's `get_by_id` eager-loads `licensures`, `educations`, and
    `certifications` via `lazy="selectin"`, so the template can render
    each sub-section without further queries.
    """
    profile = await _load_provider_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)
    return {"request": request, "profile": profile, "current_user": requesting_user}


async def handle_create_provider(
    payload: ProviderCreate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> Provider:
    """Creates a profile owned by the requesting user plus any inline
    credential sub-rows. A user may own zero, one, or many profiles —
    nothing here rejects a second create. One `CREATE_PROVIDER_PROFILE`
    audit row is written whose `after` snapshot includes the inline
    sub-rows — the snapshot schema embeds the nested credential lists,
    so a single row captures the full create.
    """
    profile_fields = payload.model_dump(
        exclude={"licensures", "educations", "certifications"}
    )
    created = await repo.create_provider(user_id=requesting_user.id, **profile_fields)

    for licensure in payload.licensures:
        await repo.add_licensure(created, **licensure.model_dump())
    for education in payload.educations:
        await repo.add_education(created, **education.model_dump())
    for certification in payload.certifications:
        await repo.add_certification(created, **certification.model_dump())

    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=created,
        resource=PROFILE,
        verb="create",
    ):
        pass
    return created


async def handle_update_provider(
    profile_id: UUID,
    payload: ProviderUpdate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> Provider:
    """Patches practice/availability fields on the profile. Owner-or-admin only."""
    profile = await _load_provider_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=profile,
        resource=PROFILE,
        verb="update",
    ):
        await repo.update_provider(profile, **payload.model_dump(exclude_unset=True))
    return profile


async def handle_delete_provider(
    profile_id: UUID,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> None:
    """Hard-deletes the profile (sub-rows cascade). Owner-or-admin only.

    The audit row is recorded before the delete fires so the actor FK is
    still valid; `before` captures the full profile including sub-rows.
    No per-sub-row audit rows — the parent's nested snapshot is the
    durable record.
    """
    profile = await _load_provider_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=profile,
        resource=PROFILE,
        verb="delete",
    ):
        await repo.delete_provider(profile)


# --- Licensure handlers --------------------------------------------------


async def handle_create_licensure(
    profile_id: UUID,
    payload: ProviderLicensureCreate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderLicensure:
    profile = await _load_provider_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    created = await repo.add_licensure(profile, **payload.model_dump())
    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=created,
        resource=LICENSURE,
        verb="create",
    ):
        pass
    return created


async def handle_update_licensure(
    profile_id: UUID,
    licensure_id: UUID,
    payload: ProviderLicensureUpdate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderLicensure:
    profile = await _load_provider_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    licensure = await _load_subrow_or_404(
        repo.get_licensure_by_id, licensure_id, profile.id, name="Licensure"
    )
    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=licensure,
        resource=LICENSURE,
        verb="update",
    ):
        await repo.update_licensure(licensure, **payload.model_dump(exclude_unset=True))
    return licensure


async def handle_delete_licensure(
    profile_id: UUID,
    licensure_id: UUID,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> None:
    profile = await _load_provider_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    licensure = await _load_subrow_or_404(
        repo.get_licensure_by_id, licensure_id, profile.id, name="Licensure"
    )
    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=licensure,
        resource=LICENSURE,
        verb="delete",
    ):
        await repo.delete_licensure(licensure)


# --- Education handlers --------------------------------------------------


async def handle_create_education(
    profile_id: UUID,
    payload: ProviderEducationCreate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderEducation:
    profile = await _load_provider_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    created = await repo.add_education(profile, **payload.model_dump())
    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=created,
        resource=EDUCATION,
        verb="create",
    ):
        pass
    return created


async def handle_update_education(
    profile_id: UUID,
    education_id: UUID,
    payload: ProviderEducationUpdate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderEducation:
    profile = await _load_provider_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    education = await _load_subrow_or_404(
        repo.get_education_by_id, education_id, profile.id, name="Education entry"
    )
    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=education,
        resource=EDUCATION,
        verb="update",
    ):
        await repo.update_education(education, **payload.model_dump(exclude_unset=True))
    return education


async def handle_delete_education(
    profile_id: UUID,
    education_id: UUID,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> None:
    profile = await _load_provider_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    education = await _load_subrow_or_404(
        repo.get_education_by_id, education_id, profile.id, name="Education entry"
    )
    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=education,
        resource=EDUCATION,
        verb="delete",
    ):
        await repo.delete_education(education)


# --- Certification handlers ----------------------------------------------


async def handle_create_certification(
    profile_id: UUID,
    payload: ProviderCertificationCreate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderCertification:
    profile = await _load_provider_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    created = await repo.add_certification(profile, **payload.model_dump())
    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=created,
        resource=CERTIFICATION,
        verb="create",
    ):
        pass
    return created


async def handle_update_certification(
    profile_id: UUID,
    certification_id: UUID,
    payload: ProviderCertificationUpdate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderCertification:
    profile = await _load_provider_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    certification = await _load_subrow_or_404(
        repo.get_certification_by_id,
        certification_id,
        profile.id,
        name="Certification",
    )
    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=certification,
        resource=CERTIFICATION,
        verb="update",
    ):
        await repo.update_certification(
            certification, **payload.model_dump(exclude_unset=True)
        )
    return certification


async def handle_delete_certification(
    profile_id: UUID,
    certification_id: UUID,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> None:
    profile = await _load_provider_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    certification = await _load_subrow_or_404(
        repo.get_certification_by_id,
        certification_id,
        profile.id,
        name="Certification",
    )
    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=certification,
        resource=CERTIFICATION,
        verb="delete",
    ):
        await repo.delete_certification(certification)
