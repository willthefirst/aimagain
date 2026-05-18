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

from src.domain.logic.favorites.repository import UserFavoriteRepository
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.providers.repository import ProviderRepository
from src.domain.logic.providers.schema import ProviderCreate, ProviderUpdate
from src.domain.logic.users.repository import UserRepository
from src.domain.models import (
    Organization,
    Provider,
    User,
)
from src.domain.specs.provider import PROVIDER_ENTITY
from src.framework.audit.repository import AuditRepository
from src.framework.dispatch.handlers import (
    handle_create,
    handle_get_edit_form,
    handle_get_new_form,
    handle_update,
)
from src.framework.dispatch.pagination import (
    DEFAULT_PAGE_SIZE,
    base_query,
    offset_for,
    paginate,
    parse_page,
)
from src.framework.http.exceptions import ForbiddenError, NotFoundError

logger = logging.getLogger(__name__)


# --- Provider handlers ----------------------------------------------------


async def _orgs_visible_to(
    org_repo: OrganizationRepository, user: User
) -> list[Organization]:
    """Return the Organizations a user may attach their Provider to.

    Owners see only the Orgs they own; superusers see every Org. Drives
    the Provider create/edit form's Org-picker dropdown and pairs with
    the wire-level ownership check in :func:`_assert_org_belongs_to`
    (#524 retro: Org ownership is the boundary for who may attach
    Providers — mirrors ``Organization.write_authz``)."""
    if user.is_superuser:
        return list(
            await org_repo.list_default(
                Organization, order_by=Organization.created_at.desc()
            )
        )
    return list(await org_repo.list_for_user(user.id))


async def _assert_org_belongs_to(
    org_repo: OrganizationRepository, *, org_id: UUID, user: User
) -> None:
    """Reject a Provider create/update whose ``org_id`` points at an Org
    the requesting user doesn't own (superusers bypass).

    404 when the Org doesn't exist (no info leak about other users' Org
    ids); 403 when it exists but belongs to someone else. Same shape as
    ``OWNER_OR_ADMIN`` on the Org row itself — attaching a Provider is
    "writing the Org's Provider list," so the same boundary applies."""
    org = await org_repo._get_by_id(Organization, org_id)
    if org is None:
        raise NotFoundError(detail=f"Organization {org_id} not found")
    if not user.is_superuser and org.owner_id != user.id:
        raise ForbiddenError(
            detail="You may only attach a Provider to an Organization you own"
        )


async def handle_get_provider_new_form(
    *,
    request: Request,
    requesting_user: User,
    organization_repo: OrganizationRepository,
) -> dict[str, Any]:
    """Provider create-form handler. Extends the framework's default by
    loading the user's visible Organizations into the context for the
    Org-picker dropdown — Provider create takes ``org_id`` (#524), and
    the form needs a populated select."""
    context = await handle_get_new_form(
        PROVIDER_ENTITY, request=request, requesting_user=requesting_user
    )
    context["orgs"] = await _orgs_visible_to(organization_repo, requesting_user)
    return context


async def handle_get_provider_edit_form(
    *,
    request: Request,
    provider_id: UUID,
    repo: ProviderRepository,
    requesting_user: User,
    organization_repo: OrganizationRepository,
) -> dict[str, Any]:
    """Provider edit-form handler. Mirror of the new-form handler — the
    Org-picker dropdown lists the user's visible Orgs, with the
    Provider's current ``org_id`` pre-selected (the template handles
    the `selected` attribute). ``provider_id`` is the URL's path param
    (``PROVIDER_ENTITY.id_param``); it's forwarded to the framework's
    ``handle_get_edit_form`` as ``target_id``."""
    context = await handle_get_edit_form(
        PROVIDER_ENTITY,
        request=request,
        target_id=provider_id,
        repo=repo,
        requesting_user=requesting_user,
    )
    context["orgs"] = await _orgs_visible_to(organization_repo, requesting_user)
    return context


async def handle_create_provider(
    *,
    payload: ProviderCreate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
    organization_repo: OrganizationRepository,
) -> Provider:
    """Provider create handler. Validates ``payload.org_id`` points at an
    Org the requesting user owns (or any Org for superusers) before
    delegating to the framework's generic ``handle_create`` — the
    dropdown only renders user-owned Orgs, so this check guards the
    wire against curl callers (#524)."""
    await _assert_org_belongs_to(
        organization_repo, org_id=payload.org_id, user=requesting_user
    )
    return await handle_create(
        PROVIDER_ENTITY,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=requesting_user,
    )


async def handle_update_provider(
    *,
    provider_id: UUID,
    payload: ProviderUpdate,
    repo: ProviderRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
    organization_repo: OrganizationRepository,
) -> Provider:
    """Provider update handler. When the PATCH payload touches
    ``org_id``, verify the new Org is owned by the requesting user
    (same rule as create). PATCHes that leave ``org_id`` unset pass
    straight through. ``provider_id`` is the URL's path param —
    forwarded to ``handle_update`` as ``target_id``."""
    if payload.org_id is not None:
        await _assert_org_belongs_to(
            organization_repo, org_id=payload.org_id, user=requesting_user
        )
    return await handle_update(
        PROVIDER_ENTITY,
        target_id=provider_id,
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=requesting_user,
    )


async def provider_detail_extras(
    *,
    target: Provider,
    requesting_user: User | None,
    user_favorite_repo: UserFavoriteRepository,
    **_: Any,
) -> dict[str, Any]:
    """Per-viewer detail extras for `make_detail_handler(PROVIDER_ENTITY)`.

    `is_favorited` is a property of the (viewer, provider) pair, not of
    the provider — it lives in context, not on the model. Anonymous
    viewers (`requesting_user is None` for a hypothetical public detail)
    get `False` without a DB round-trip; today `PROVIDER_ENTITY.read_user_dep`
    forces auth, but the None-check keeps the helper safe if that ever
    changes.
    """
    if requesting_user is None:
        return {"is_favorited": False}
    return {
        "is_favorited": await user_favorite_repo.is_favorited(
            user_id=requesting_user.id, provider_id=target.id
        )
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

    Pagination: parses `?page=N` and asks the repo for `per_page + 1`
    rows to compute `has_next`. Uses the framework's
    `DEFAULT_PAGE_SIZE` — this is a bespoke handler so there's no
    `EntitySpec.page_size` to consult.
    """
    if user_id != requesting_user.id and not requesting_user.is_superuser:
        raise ForbiddenError(
            detail="Only the target user or an admin may view their providers"
        )
    target_user = await user_repo.get_by_model_id(User, user_id)
    if target_user is None:
        raise NotFoundError(detail=f"User {user_id} not found")
    page_number = parse_page(request)
    per_page = DEFAULT_PAGE_SIZE
    providers_plus_one = await repo.list_for_user(
        user_id,
        offset=offset_for(page_number, per_page),
        limit=per_page + 1,
    )
    providers, page_meta = paginate(
        providers_plus_one, page=page_number, per_page=per_page
    )
    return {
        "request": request,
        "target_user": target_user,
        "providers": providers,
        "is_self": user_id == requesting_user.id,
        "current_user": requesting_user,
        "page_meta": page_meta,
        "paginator_base_query": base_query(request),
    }
