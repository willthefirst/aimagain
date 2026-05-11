"""Provider-provider orchestration handlers.

One file per resource family — the parent provider plus its three credential
sub-tables (licensure, education, certification). Each mutation handler
owns the transaction commit and writes a single audit row covering the
mutation, per `RESOURCE_GRAMMAR.md:135` and the discipline enforced in
`test_audit_discipline.py`.

Authorization is uniform: a provider can mutate only their own provider and
its sub-rows; a superuser can mutate any. Read handlers are open to any
authenticated user.

Sub-resource handlers also assert that the URL's `provider_id` matches the
sub-row's `provider_id`. Without this, `/providers/A/licensures/B` would
silently mutate a licensure belonging to a different provider.
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import Request

from src.api.common.exceptions import ForbiddenError, NotFoundError
from src.api.common.specs.provider import PROVIDER_ENTITY
from src.api.common.specs.provider_certification import CERTIFICATION_ENTITY
from src.api.common.specs.provider_education import EDUCATION_ENTITY
from src.api.common.specs.provider_licensure import LICENSURE_ENTITY
from src.logic._authz import assert_owner_or_admin, is_admin, is_owner
from src.logic.audit import mutate
from src.models import (
    Provider,
    User,
)
from src.repositories.audit_repository import AuditRepository
from src.repositories.favorites.user_favorite_repository import UserFavoriteRepository
from src.repositories.providers.provider_repository import ProviderRepository
from src.repositories.users.user_repository import UserRepository
from src.schemas.providers.provider import (
    ProviderCreate,
)

logger = logging.getLogger(__name__)


# --- Audited-resource bindings -------------------------------------------
#
# The four declarations themselves now live in
# `src/api/common/specs/<entity>.py`; these module-level constants are
# thin re-exports so handler bodies can keep their existing
# `resource=PROVIDER` / `resource=LICENSURE` shape without churn. The
# spec is the source of truth.


PROVIDER = PROVIDER_ENTITY.audit
LICENSURE = LICENSURE_ENTITY.audit
EDUCATION = EDUCATION_ENTITY.audit
CERTIFICATION = CERTIFICATION_ENTITY.audit


async def _load_provider_or_404(
    provider_id: UUID, repo: ProviderRepository
) -> Provider:
    provider = await repo.get_by_id(provider_id)
    if provider is None:
        raise NotFoundError(detail="Provider not found")
    return provider


# --- Provider handlers ----------------------------------------------------


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
    providers = await repo.list_providers(
        license_type=license_type, issuing_state=issuing_state
    )
    return {
        "request": request,
        "providers": providers,
        "selected_license_type": license_type,
        "selected_issuing_state": issuing_state,
    }


async def handle_get_provider_detail(
    request: Request,
    provider_id: UUID,
    repo: ProviderRepository,
    user_favorite_repo: UserFavoriteRepository,
    requesting_user: User,
) -> dict[str, Any]:
    """Loads any provider by id for the read-only detail page; 404 if missing.

    The repo's `get_by_id` eager-loads `licensures`, `educations`, and
    `certifications` via `lazy="selectin"`, so the template can render
    each sub-section without further queries.

    Per-viewer derived fields live in the context dict, not on `provider`
    itself — `is_favorited` is a property of the (viewer, provider) pair,
    not of the provider. Same shape as `can_edit`. Anonymous viewers
    (`requesting_user is None`) get `is_favorited=False` without a DB
    round-trip.
    """
    provider = await _load_provider_or_404(provider_id, repo)
    can_edit = is_owner(provider, requesting_user) or is_admin(requesting_user)
    if requesting_user is None:
        is_favorited = False
    else:
        is_favorited = await user_favorite_repo.is_favorited(
            user_id=requesting_user.id, provider_id=provider.id
        )
    return {
        "request": request,
        "provider": provider,
        "current_user": requesting_user,
        "can_edit": can_edit,
        "is_favorited": is_favorited,
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
    providers = await repo.list_for_user(user_id)
    return {
        "request": request,
        "target_user": target_user,
        "providers": providers,
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
    creating a provider doesn't need to load anything from the db.
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
    """Loads a provider for the edit-form page. 404 if missing, 403 if the
    requester is neither owner nor admin (mirrors `assert_owner_or_admin`).

    The repo's `get_by_id` eager-loads `licensures`, `educations`, and
    `certifications` via `lazy="selectin"`, so the template can render
    each sub-section without further queries.
    """
    provider = await _load_provider_or_404(provider_id, repo)
    assert_owner_or_admin(provider, requesting_user, action="modify this provider")
    return {"request": request, "provider": provider, "current_user": requesting_user}


async def handle_create_provider(
    payload: ProviderCreate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> Provider:
    """Creates a provider owned by the requesting user plus any inline
    credential sub-rows. A user may own zero, one, or many providers —
    nothing here rejects a second create. One `CREATE_PROVIDER`
    audit row is written whose `after` snapshot includes the inline
    sub-rows — the snapshot schema embeds the nested credential lists,
    so a single row captures the full create.
    """
    provider_fields = payload.model_dump(
        exclude={"licensures", "educations", "certifications"}
    )
    created = await repo.create_provider(user_id=requesting_user.id, **provider_fields)

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
        resource=PROVIDER,
        verb="create",
    ):
        pass
    return created
