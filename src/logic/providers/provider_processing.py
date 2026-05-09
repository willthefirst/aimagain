"""Provider-profile orchestration handlers.

One file per resource family — the parent profile plus its three credential
sub-tables (licensure, education, certification). Each mutation handler
owns the transaction commit and writes a single audit row covering the
mutation, per `RESOURCE_GRAMMAR.md:135` and the discipline enforced in
`test_audit_discipline.py`.

Authorization is uniform: a provider can mutate only their own profile and
its sub-rows; a superuser can mutate any. Read handlers are open to any
authenticated user.

Sub-resource handlers also assert that the URL's `provider_id` matches the
sub-row's `provider_id`. Without this, `/profiles/A/licensures/B` would
silently mutate a licensure belonging to a different profile.
"""

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel

from src.api.common.exceptions import ForbiddenError, NotFoundError
from src.logic._authz import assert_owner_or_admin, is_admin, is_owner
from src.logic.audit import AuditAction, AuditedResource, make_snapshotter, mutate
from src.models import (
    Provider,
    ProviderCertification,
    ProviderEducation,
    ProviderLicensure,
    User,
)
from src.repositories.audit_repository import AuditRepository
from src.repositories.providers.provider_repository import ProviderRepository
from src.repositories.users.user_repository import UserRepository
from src.schemas.providers.provider import (
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


PROFILE = AuditedResource(
    type="provider_profile",
    snapshot=make_snapshotter(ProviderAuditSnapshot),
    create=AuditAction.CREATE_PROVIDER,
    update=AuditAction.UPDATE_PROVIDER,
    delete=AuditAction.DELETE_PROVIDER,
)
LICENSURE = AuditedResource(
    type="provider_licensure",
    snapshot=make_snapshotter(ProviderLicensureAuditSnapshot),
    create=AuditAction.CREATE_LICENSURE,
    update=AuditAction.UPDATE_LICENSURE,
    delete=AuditAction.DELETE_LICENSURE,
)
EDUCATION = AuditedResource(
    type="provider_education",
    snapshot=make_snapshotter(ProviderEducationAuditSnapshot),
    create=AuditAction.CREATE_EDUCATION,
    update=AuditAction.UPDATE_EDUCATION,
    delete=AuditAction.DELETE_EDUCATION,
)
CERTIFICATION = AuditedResource(
    type="provider_certification",
    snapshot=make_snapshotter(ProviderCertificationAuditSnapshot),
    create=AuditAction.CREATE_CERTIFICATION,
    update=AuditAction.UPDATE_CERTIFICATION,
    delete=AuditAction.DELETE_CERTIFICATION,
)


async def _load_provider_or_404(
    provider_id: UUID, repo: ProviderRepository
) -> Provider:
    profile = await repo.get_by_id(provider_id)
    if profile is None:
        raise NotFoundError(detail="Provider not found")
    return profile


async def _load_subrow_or_404(getter, sub_id: UUID, parent_id: UUID, *, name: str):
    """Load a credential sub-row and verify its `provider_id` matches the
    URL's `provider_id`. 404 if missing or if the FK is for a different
    parent — without this, `/profiles/A/licensures/B` would silently
    mutate a sub-row owned by profile B."""
    row = await getter(sub_id)
    if row is None or row.provider_id != parent_id:
        raise NotFoundError(detail=f"{name} not found")
    return row


# --- Profile handlers ----------------------------------------------------


async def handle_list_providers(
    request: Request,
    repo: ProviderRepository,
    requesting_user: User | None = None,
    license_type: str | None = None,
    issuing_state: str | None = None,
) -> dict[str, Any]:
    """Public listing — no auth gate, no audit, no commit. Returns the
    template context for the HTML list page; the active filter values are
    forwarded so the template can preselect them in its filter form.

    `requesting_user` is `None` for this handler — `mount_list(...,
    public=True)` skips the auth dep — but the kwarg is accepted for
    uniformity with the mount contract.
    """
    del requesting_user  # explicitly unused — public route
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
    provider_id: UUID,
    repo: ProviderRepository,
    requesting_user: User,
) -> dict[str, Any]:
    """Loads any profile by id for the read-only detail page; 404 if missing.

    The repo's `get_by_id` eager-loads `licensures`, `educations`, and
    `certifications` via `lazy="selectin"`, so the template can render
    each sub-section without further queries.
    """
    profile = await _load_provider_or_404(provider_id, repo)
    can_edit = is_owner(profile, requesting_user, owner_attr="user_id") or is_admin(
        requesting_user
    )
    return {
        "request": request,
        "profile": profile,
        "current_user": requesting_user,
        "can_edit": can_edit,
    }


async def handle_list_user_providers(
    request: Request,
    user_id: UUID,
    repo: ProviderRepository,
    user_repo: UserRepository,
    requesting_user: User,
) -> dict[str, Any]:
    """Returns the template context for the user-scoped provider
    list page. A user may view their own list; admins may view anyone's.
    404 if the target user does not exist; 403 if a non-admin requests
    another user's list.
    """
    if user_id != requesting_user.id and not requesting_user.is_superuser:
        raise ForbiddenError(
            detail="Only the target user or an admin may view their providers"
        )
    target_user = await user_repo.get_user_by_id(user_id)
    if target_user is None:
        raise NotFoundError(detail=f"User {user_id} not found")
    profiles = await repo.list_for_user(user_id)
    return {
        "request": request,
        "target_user": target_user,
        "profiles": profiles,
        "is_self": user_id == requesting_user.id,
        "current_user": requesting_user,
    }


async def handle_get_provider_form(
    request: Request,
    requesting_user: User,
    repo: ProviderRepository | None = None,
) -> dict[str, Any]:
    """Builds the template context for the create-provider form.

    `repo` is accepted for uniformity with the mount_form contract (every
    form handler gets the resource's primary repo) but not used here —
    creating a profile doesn't need to load anything from the db.
    """
    del repo  # explicitly unused
    return {
        "request": request,
        "current_user": requesting_user,
        # `providers/new.html` calls `field_for(schema, ...)` against
        # this Pydantic class; pass it explicitly rather than via a
        # core-level Jinja global so schemas stay opt-in per template
        # (and core doesn't need to import schemas).
        "schema": ProviderCreate,
    }


async def handle_get_provider_edit_form(
    request: Request,
    provider_id: UUID,
    repo: ProviderRepository,
    requesting_user: User,
) -> dict[str, Any]:
    """Loads a profile for the edit-form page. 404 if missing, 403 if the
    requester is neither owner nor admin (mirrors `assert_owner_or_admin`).

    The repo's `get_by_id` eager-loads `licensures`, `educations`, and
    `certifications` via `lazy="selectin"`, so the template can render
    each sub-section without further queries.
    """
    profile = await _load_provider_or_404(provider_id, repo)
    assert_owner_or_admin(
        profile, requesting_user, owner_attr="user_id", action="modify this provider"
    )
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
    provider_id: UUID,
    payload: ProviderUpdate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> Provider:
    """Patches practice/availability fields on the profile. Owner-or-admin only."""
    profile = await _load_provider_or_404(provider_id, repo)
    assert_owner_or_admin(
        profile, requesting_user, owner_attr="user_id", action="modify this provider"
    )

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
    provider_id: UUID,
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
    profile = await _load_provider_or_404(provider_id, repo)
    assert_owner_or_admin(
        profile, requesting_user, owner_attr="user_id", action="modify this provider"
    )

    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=profile,
        resource=PROFILE,
        verb="delete",
    ):
        await repo.delete_provider(profile)


# --- Sub-row CRUD helpers ------------------------------------------------
# Three private helpers parameterized by `_SubrowSpec` cover the nine public
# sub-row handlers below. Each public handler is a thin wrapper that
# preserves its existing signature so route callers and tests don't change.


@dataclass(frozen=True)
class _SubrowSpec:
    resource: AuditedResource
    add: str
    update: str
    delete: str
    get_by_id: str
    display_name: str


_LICENSURE_SPEC = _SubrowSpec(
    resource=LICENSURE,
    add="add_licensure",
    update="update_licensure",
    delete="delete_licensure",
    get_by_id="get_licensure_by_id",
    display_name="Licensure",
)
_EDUCATION_SPEC = _SubrowSpec(
    resource=EDUCATION,
    add="add_education",
    update="update_education",
    delete="delete_education",
    get_by_id="get_education_by_id",
    display_name="Education entry",
)
_CERTIFICATION_SPEC = _SubrowSpec(
    resource=CERTIFICATION,
    add="add_certification",
    update="update_certification",
    delete="delete_certification",
    get_by_id="get_certification_by_id",
    display_name="Certification",
)


async def _handle_subrow_create(
    *,
    provider_id: UUID,
    payload: BaseModel,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
    spec: _SubrowSpec,
) -> Any:
    profile = await _load_provider_or_404(provider_id, repo)
    assert_owner_or_admin(
        profile, requesting_user, owner_attr="user_id", action="modify this provider"
    )

    created = await getattr(repo, spec.add)(profile, **payload.model_dump())
    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=created,
        resource=spec.resource,
        verb="create",
    ):
        pass
    return created


async def _handle_subrow_update(
    *,
    provider_id: UUID,
    child_id: UUID,
    payload: BaseModel,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
    spec: _SubrowSpec,
) -> Any:
    profile = await _load_provider_or_404(provider_id, repo)
    assert_owner_or_admin(
        profile, requesting_user, owner_attr="user_id", action="modify this provider"
    )

    row = await _load_subrow_or_404(
        getattr(repo, spec.get_by_id), child_id, profile.id, name=spec.display_name
    )
    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=row,
        resource=spec.resource,
        verb="update",
    ):
        await getattr(repo, spec.update)(row, **payload.model_dump(exclude_unset=True))
    return row


async def _handle_subrow_delete(
    *,
    provider_id: UUID,
    child_id: UUID,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
    spec: _SubrowSpec,
) -> None:
    profile = await _load_provider_or_404(provider_id, repo)
    assert_owner_or_admin(
        profile, requesting_user, owner_attr="user_id", action="modify this provider"
    )

    row = await _load_subrow_or_404(
        getattr(repo, spec.get_by_id), child_id, profile.id, name=spec.display_name
    )
    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=row,
        resource=spec.resource,
        verb="delete",
    ):
        await getattr(repo, spec.delete)(row)


# --- Licensure handlers --------------------------------------------------


async def handle_create_licensure(
    provider_id: UUID,
    payload: ProviderLicensureCreate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderLicensure:
    return await _handle_subrow_create(
        provider_id=provider_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=requesting_user,
        spec=_LICENSURE_SPEC,
    )


async def handle_update_licensure(
    provider_id: UUID,
    licensure_id: UUID,
    payload: ProviderLicensureUpdate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderLicensure:
    return await _handle_subrow_update(
        provider_id=provider_id,
        child_id=licensure_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=requesting_user,
        spec=_LICENSURE_SPEC,
    )


async def handle_delete_licensure(
    provider_id: UUID,
    licensure_id: UUID,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> None:
    await _handle_subrow_delete(
        provider_id=provider_id,
        child_id=licensure_id,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=requesting_user,
        spec=_LICENSURE_SPEC,
    )


# --- Education handlers --------------------------------------------------


async def handle_create_education(
    provider_id: UUID,
    payload: ProviderEducationCreate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderEducation:
    return await _handle_subrow_create(
        provider_id=provider_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=requesting_user,
        spec=_EDUCATION_SPEC,
    )


async def handle_update_education(
    provider_id: UUID,
    education_id: UUID,
    payload: ProviderEducationUpdate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderEducation:
    return await _handle_subrow_update(
        provider_id=provider_id,
        child_id=education_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=requesting_user,
        spec=_EDUCATION_SPEC,
    )


async def handle_delete_education(
    provider_id: UUID,
    education_id: UUID,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> None:
    await _handle_subrow_delete(
        provider_id=provider_id,
        child_id=education_id,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=requesting_user,
        spec=_EDUCATION_SPEC,
    )


# --- Certification handlers ----------------------------------------------


async def handle_create_certification(
    provider_id: UUID,
    payload: ProviderCertificationCreate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderCertification:
    return await _handle_subrow_create(
        provider_id=provider_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=requesting_user,
        spec=_CERTIFICATION_SPEC,
    )


async def handle_update_certification(
    provider_id: UUID,
    certification_id: UUID,
    payload: ProviderCertificationUpdate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> ProviderCertification:
    return await _handle_subrow_update(
        provider_id=provider_id,
        child_id=certification_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=requesting_user,
        spec=_CERTIFICATION_SPEC,
    )


async def handle_delete_certification(
    provider_id: UUID,
    certification_id: UUID,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> None:
    await _handle_subrow_delete(
        provider_id=provider_id,
        child_id=certification_id,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=requesting_user,
        spec=_CERTIFICATION_SPEC,
    )
