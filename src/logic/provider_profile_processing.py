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
from typing import Any, Sequence
from uuid import UUID

from fastapi import Request

from src.api.common.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.logic.audit import AuditAction, record_audit
from src.models import (
    ProviderCertification,
    ProviderEducation,
    ProviderLicensure,
    ProviderProfile,
    User,
)
from src.repositories.audit_repository import AuditRepository
from src.repositories.provider_profile_repository import ProviderProfileRepository
from src.schemas.provider_profile import (
    ProviderCertificationAuditSnapshot,
    ProviderCertificationCreate,
    ProviderCertificationUpdate,
    ProviderEducationAuditSnapshot,
    ProviderEducationCreate,
    ProviderEducationUpdate,
    ProviderLicensureAuditSnapshot,
    ProviderLicensureCreate,
    ProviderLicensureUpdate,
    ProviderProfileAuditSnapshot,
    ProviderProfileCreate,
    ProviderProfileUpdate,
)

logger = logging.getLogger(__name__)


# --- Snapshot helpers ----------------------------------------------------


def _snapshot_profile(profile: ProviderProfile) -> dict[str, Any]:
    return ProviderProfileAuditSnapshot.model_validate(profile).model_dump(mode="json")


def _snapshot_licensure(licensure: ProviderLicensure) -> dict[str, Any]:
    return ProviderLicensureAuditSnapshot.model_validate(licensure).model_dump(
        mode="json"
    )


def _snapshot_education(education: ProviderEducation) -> dict[str, Any]:
    return ProviderEducationAuditSnapshot.model_validate(education).model_dump(
        mode="json"
    )


def _snapshot_certification(cert: ProviderCertification) -> dict[str, Any]:
    return ProviderCertificationAuditSnapshot.model_validate(cert).model_dump(
        mode="json"
    )


# --- Authorization helper ------------------------------------------------


def _assert_can_mutate(profile: ProviderProfile, user: User) -> None:
    if profile.user_id != user.id and not user.is_superuser:
        raise ForbiddenError(
            detail="Only the profile owner or an admin can perform this action"
        )


async def _load_profile_or_404(
    profile_id: UUID, repo: ProviderProfileRepository
) -> ProviderProfile:
    profile = await repo.get_by_id(profile_id)
    if profile is None:
        raise NotFoundError(detail="Provider profile not found")
    return profile


# --- Profile handlers ----------------------------------------------------


async def handle_list_profiles(
    repo: ProviderProfileRepository,
    *,
    license_type: str | None = None,
    issuing_state: str | None = None,
) -> Sequence[ProviderProfile]:
    """Public listing — no auth gate, no audit, no commit."""
    return await repo.list_profiles(
        license_type=license_type, issuing_state=issuing_state
    )


async def handle_get_profile(
    profile_id: UUID,
    repo: ProviderProfileRepository,
    requesting_user: User,
) -> ProviderProfile:
    """Authenticated read of any profile by id; 404 if missing."""
    return await _load_profile_or_404(profile_id, repo)


async def handle_get_my_profile(
    repo: ProviderProfileRepository,
    requesting_user: User,
) -> ProviderProfile:
    """Returns the requesting user's profile; 404 if they have not created one yet
    (profiles are not auto-created on registration)."""
    profile = await repo.get_by_user_id(requesting_user.id)
    if profile is None:
        raise NotFoundError(detail="You do not have a provider profile yet")
    return profile


async def handle_get_provider_profile_form(
    request: Request,
    requesting_user: User,
) -> dict[str, Any]:
    """Builds the template context for the create-provider-profile form."""
    return {"request": request, "current_user": requesting_user}


async def handle_get_provider_profile_edit_form(
    request: Request,
    profile_id: UUID,
    repo: ProviderProfileRepository,
    requesting_user: User,
) -> dict[str, Any]:
    """Loads a profile for the edit-form page. 404 if missing, 403 if the
    requester is neither owner nor admin (mirrors `_assert_can_mutate`).

    The repo's `get_by_id` eager-loads `licensures`, `educations`, and
    `certifications` via `lazy="selectin"`, so the template can render
    each sub-section without further queries.
    """
    profile = await _load_profile_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)
    return {"request": request, "profile": profile, "current_user": requesting_user}


async def handle_create_profile(
    payload: ProviderProfileCreate,
    repo: ProviderProfileRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderProfile:
    """Creates the requesting user's profile plus any inline credential sub-rows.

    400 if the user already has a profile (the `uq_provider_profiles_user_id`
    constraint would catch this at the DB; we surface a clean message
    instead of an integrity error). One `CREATE_PROVIDER_PROFILE` audit row
    is written whose `after` snapshot includes the inline sub-rows — the
    snapshot schema embeds the nested credential lists, so a single row
    captures the full create.
    """
    if await repo.get_by_user_id(requesting_user.id) is not None:
        raise BadRequestError(detail="User already has a provider profile")

    profile_fields = payload.model_dump(
        exclude={"licensures", "educations", "certifications"}
    )
    created = await repo.create_profile(user_id=requesting_user.id, **profile_fields)

    for licensure in payload.licensures:
        await repo.add_licensure(created, **licensure.model_dump())
    for education in payload.educations:
        await repo.add_education(created, **education.model_dump())
    for certification in payload.certifications:
        await repo.add_certification(created, **certification.model_dump())

    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type="provider_profile",
        resource_id=created.id,
        action=AuditAction.CREATE_PROVIDER_PROFILE,
        before=None,
        after=_snapshot_profile(created),
    )
    await repo.session.commit()
    logger.info(
        f"Handler: user {requesting_user.id} created provider profile {created.id}"
    )
    return created


async def handle_update_profile(
    profile_id: UUID,
    payload: ProviderProfileUpdate,
    repo: ProviderProfileRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderProfile:
    """Patches practice/availability fields on the profile. Owner-or-admin only."""
    profile = await _load_profile_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    before = _snapshot_profile(profile)
    updated = await repo.update_profile(
        profile, **payload.model_dump(exclude_unset=True)
    )
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type="provider_profile",
        resource_id=updated.id,
        action=AuditAction.UPDATE_PROVIDER_PROFILE,
        before=before,
        after=_snapshot_profile(updated),
    )
    await repo.session.commit()
    logger.info(
        f"Handler: user {requesting_user.id} updated provider profile {updated.id}"
    )
    return updated


async def handle_delete_profile(
    profile_id: UUID,
    repo: ProviderProfileRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> None:
    """Hard-deletes the profile (sub-rows cascade). Owner-or-admin only.

    The audit row is recorded before the delete fires so the actor FK is
    still valid; `before` captures the full profile including sub-rows.
    No per-sub-row audit rows — the parent's nested snapshot is the
    durable record.
    """
    profile = await _load_profile_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    before = _snapshot_profile(profile)
    target_id = profile.id
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type="provider_profile",
        resource_id=target_id,
        action=AuditAction.DELETE_PROVIDER_PROFILE,
        before=before,
        after=None,
    )
    await repo.delete_profile(profile)
    await repo.session.commit()
    logger.info(
        f"Handler: user {requesting_user.id} deleted provider profile {target_id}"
    )


# --- Licensure handlers --------------------------------------------------


async def handle_create_licensure(
    profile_id: UUID,
    payload: ProviderLicensureCreate,
    repo: ProviderProfileRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderLicensure:
    profile = await _load_profile_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    created = await repo.add_licensure(profile, **payload.model_dump())
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type="provider_licensure",
        resource_id=created.id,
        action=AuditAction.CREATE_LICENSURE,
        before=None,
        after=_snapshot_licensure(created),
    )
    await repo.session.commit()
    return created


async def handle_update_licensure(
    profile_id: UUID,
    licensure_id: UUID,
    payload: ProviderLicensureUpdate,
    repo: ProviderProfileRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderLicensure:
    profile = await _load_profile_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    licensure = await repo.get_licensure_by_id(licensure_id)
    if licensure is None or licensure.profile_id != profile.id:
        raise NotFoundError(detail="Licensure not found")

    before = _snapshot_licensure(licensure)
    updated = await repo.update_licensure(
        licensure, **payload.model_dump(exclude_unset=True)
    )
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type="provider_licensure",
        resource_id=updated.id,
        action=AuditAction.UPDATE_LICENSURE,
        before=before,
        after=_snapshot_licensure(updated),
    )
    await repo.session.commit()
    return updated


async def handle_delete_licensure(
    profile_id: UUID,
    licensure_id: UUID,
    repo: ProviderProfileRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> None:
    profile = await _load_profile_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    licensure = await repo.get_licensure_by_id(licensure_id)
    if licensure is None or licensure.profile_id != profile.id:
        raise NotFoundError(detail="Licensure not found")

    before = _snapshot_licensure(licensure)
    target_id = licensure.id
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type="provider_licensure",
        resource_id=target_id,
        action=AuditAction.DELETE_LICENSURE,
        before=before,
        after=None,
    )
    await repo.delete_licensure(licensure)
    await repo.session.commit()


# --- Education handlers --------------------------------------------------


async def handle_create_education(
    profile_id: UUID,
    payload: ProviderEducationCreate,
    repo: ProviderProfileRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderEducation:
    profile = await _load_profile_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    created = await repo.add_education(profile, **payload.model_dump())
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type="provider_education",
        resource_id=created.id,
        action=AuditAction.CREATE_EDUCATION,
        before=None,
        after=_snapshot_education(created),
    )
    await repo.session.commit()
    return created


async def handle_update_education(
    profile_id: UUID,
    education_id: UUID,
    payload: ProviderEducationUpdate,
    repo: ProviderProfileRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderEducation:
    profile = await _load_profile_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    education = await repo.get_education_by_id(education_id)
    if education is None or education.profile_id != profile.id:
        raise NotFoundError(detail="Education entry not found")

    before = _snapshot_education(education)
    updated = await repo.update_education(
        education, **payload.model_dump(exclude_unset=True)
    )
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type="provider_education",
        resource_id=updated.id,
        action=AuditAction.UPDATE_EDUCATION,
        before=before,
        after=_snapshot_education(updated),
    )
    await repo.session.commit()
    return updated


async def handle_delete_education(
    profile_id: UUID,
    education_id: UUID,
    repo: ProviderProfileRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> None:
    profile = await _load_profile_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    education = await repo.get_education_by_id(education_id)
    if education is None or education.profile_id != profile.id:
        raise NotFoundError(detail="Education entry not found")

    before = _snapshot_education(education)
    target_id = education.id
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type="provider_education",
        resource_id=target_id,
        action=AuditAction.DELETE_EDUCATION,
        before=before,
        after=None,
    )
    await repo.delete_education(education)
    await repo.session.commit()


# --- Certification handlers ----------------------------------------------


async def handle_create_certification(
    profile_id: UUID,
    payload: ProviderCertificationCreate,
    repo: ProviderProfileRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderCertification:
    profile = await _load_profile_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    created = await repo.add_certification(profile, **payload.model_dump())
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type="provider_certification",
        resource_id=created.id,
        action=AuditAction.CREATE_CERTIFICATION,
        before=None,
        after=_snapshot_certification(created),
    )
    await repo.session.commit()
    return created


async def handle_update_certification(
    profile_id: UUID,
    certification_id: UUID,
    payload: ProviderCertificationUpdate,
    repo: ProviderProfileRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderCertification:
    profile = await _load_profile_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    certification = await repo.get_certification_by_id(certification_id)
    if certification is None or certification.profile_id != profile.id:
        raise NotFoundError(detail="Certification not found")

    before = _snapshot_certification(certification)
    updated = await repo.update_certification(
        certification, **payload.model_dump(exclude_unset=True)
    )
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type="provider_certification",
        resource_id=updated.id,
        action=AuditAction.UPDATE_CERTIFICATION,
        before=before,
        after=_snapshot_certification(updated),
    )
    await repo.session.commit()
    return updated


async def handle_delete_certification(
    profile_id: UUID,
    certification_id: UUID,
    repo: ProviderProfileRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> None:
    profile = await _load_profile_or_404(profile_id, repo)
    _assert_can_mutate(profile, requesting_user)

    certification = await repo.get_certification_by_id(certification_id)
    if certification is None or certification.profile_id != profile.id:
        raise NotFoundError(detail="Certification not found")

    before = _snapshot_certification(certification)
    target_id = certification.id
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type="provider_certification",
        resource_id=target_id,
        action=AuditAction.DELETE_CERTIFICATION,
        before=before,
        after=None,
    )
    await repo.delete_certification(certification)
    await repo.session.commit()
