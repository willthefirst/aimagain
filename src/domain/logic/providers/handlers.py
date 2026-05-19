"""Provider-provider orchestration handlers.

One file per resource family — the parent provider plus its three credential
sub-tables (licensure, education, certification). Each mutation handler
owns the transaction commit and writes a single audit row covering the
mutation, per `RESOURCE_GRAMMAR.md:135` and the discipline enforced in
`test_audit_discipline.py`.

Authorization is uniform: a provider can mutate only their own provider and
its sub-rows; a superuser can mutate any. Read handlers are open to any
authenticated user.

Sub-resource handlers also assert URL-vs-row consistency so that
`/providers/A/licensures/B` cannot mutate a licensure belonging to a
different provider. After #635 PR A credentials FK to `clinicians.id`,
not `providers.id`; the consistency check loads the URL's provider and
compares `licensure.clinician_id == provider.clinician_id`. Wired through
`EntitySpec.child_parent_match_attr="clinician_id"` on the credential
specs in `src/domain/specs/_credential.py`.

The wire-level "you may only attach a Provider to an Org you own" rule
is declared on `PROVIDER_ENTITY.payload_authz_path` and resolved to
:func:`_assert_provider_payload_org_ownership` below — the framework
invokes it from the factory-built create / update handlers, so the
route file no longer overrides those verbs.
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel

from src.domain.logic.favorites.repository import UserFavoriteRepository
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.providers.repository import ProviderRepository
from src.domain.logic.users.repository import UserRepository
from src.domain.models import (
    Organization,
    Provider,
    User,
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
    the wire-level ownership check in
    :func:`_assert_provider_payload_org_ownership` (#524 retro: Org
    ownership is the boundary for who may attach Providers — mirrors
    ``Organization.write_authz``)."""
    if user.is_superuser:
        return list(
            await org_repo.list_default(
                Organization, order_by=Organization.created_at.desc()
            )
        )
    return list(await org_repo.list_for_user(user.id))


async def _assert_provider_payload_org_ownership(
    *,
    payload: BaseModel,
    requesting_user: User,
    organization_repo: OrganizationRepository,
) -> None:
    """`PROVIDER_ENTITY.payload_authz_path` target — reject a Provider
    create/update whose ``org_id`` points at an Org the requesting user
    doesn't own (superusers bypass).

    404 when the Org doesn't exist (no info leak about other users' Org
    ids); 403 when it exists but belongs to someone else. Same shape as
    ``OWNER_OR_ADMIN`` on the Org row itself — attaching a Provider is
    "writing the Org's Provider list," so the same boundary applies.

    The framework invokes this from both `handle_create` and
    `handle_update`. PATCH payloads where ``org_id`` is None (i.e. the
    PATCH doesn't touch the FK) are a no-op — only flow through the
    ownership check when the payload is actually trying to set a new
    Org."""
    org_id = getattr(payload, "org_id", None)
    if org_id is None:
        return
    org = await organization_repo._get_by_id(Organization, org_id)
    if org is None:
        raise NotFoundError(detail=f"Organization {org_id} not found")
    if not requesting_user.is_superuser and org.owner_id != requesting_user.id:
        raise ForbiddenError(
            detail="You may only attach a Provider to an Organization you own"
        )


async def provider_form_extras(
    *,
    target: Provider | None,
    requesting_user: User,
    organization_repo: OrganizationRepository,
    **_: Any,
) -> dict[str, Any]:
    """Per-viewer form extras for `make_new_form_handler` /
    `make_edit_form_handler` against `PROVIDER_ENTITY`.

    Loads the requesting user's visible Organizations into the context
    for the Org-picker dropdown — Provider create/update takes
    ``org_id``, and the form needs a populated select. The
    framework invokes this on both the create path (``target=None``)
    and the edit path (``target=<provider row>``); the dropdown is the
    same either way — the template handles pre-selecting the row's
    current ``org_id`` via the standard `selected` attribute.
    """
    return {
        "orgs": await _orgs_visible_to(organization_repo, requesting_user),
    }


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
