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
`/clinicians/A/licensures/B` cannot mutate a licensure belonging to a
different clinician directory entry (URL family renamed in #642 PR 4
— the model class stays `Provider`). After #635 PR A credentials FK to
`clinicians.id`,
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
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import (
    Organization,
    Provider,
    User,
)
from src.framework.authz import assert_fk_ownership, list_visible_to
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


async def _assert_provider_payload_org_ownership(
    *,
    payload: BaseModel,
    requesting_user: User,
    organization_repo: OrganizationRepository,
) -> None:
    """`PROVIDER_ENTITY.payload_authz_path` target.

    Solo-practice path (#699): when ``payload.solo_practice`` is True,
    auto-create a solo-practice Organization named after the clinician
    and patch ``payload.org_id`` so the framework's model constructor
    gets a real FK. Skips the ownership check since we just created it.

    Normal path: delegate to the framework's generic FK-ownership guard.
    """
    if getattr(payload, "solo_practice", False):
        first = (getattr(payload, "first_name", None) or "").strip()
        last = (getattr(payload, "last_name", None) or "").strip()
        name_parts = [p for p in (first, last) if p]
        org_name = " ".join(name_parts) if name_parts else requesting_user.username
        auto_org = Organization(
            name=org_name,
            type="solo_practice",
            owner_id=requesting_user.id,
        )
        created_org = await organization_repo.create(auto_org)
        payload.org_id = created_org.id
        return
    await assert_fk_ownership(
        payload=payload,
        attr="org_id",
        requesting_user=requesting_user,
        parent_repo=organization_repo,
        parent_model=Organization,
        parent_noun="Organization",
        child_noun="Provider",
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
        "orgs": await list_visible_to(organization_repo, requesting_user, Organization),
    }


async def provider_detail_extras(
    *,
    target: Provider,
    requesting_user: User | None,
    user_favorite_repo: UserFavoriteRepository,
    verification_repo: VerificationRepository,
    **_: Any,
) -> dict[str, Any]:
    """Per-viewer detail extras for `make_detail_handler(PROVIDER_ENTITY)`.

    `is_favorited` is a property of the (viewer, provider) pair; anonymous
    viewers get `False`. `verification_status` is the outcome of the most
    recent nightly run (`verified` / `needs_review` / `failed`) or `None`
    when no run has happened yet (#707).
    """
    latest = await verification_repo.latest_for_provider(target.id)
    verification_status = latest.status if latest else None
    if requesting_user is None:
        return {"is_favorited": False, "verification_status": verification_status}
    return {
        "is_favorited": await user_favorite_repo.is_favorited(
            user_id=requesting_user.id, provider_id=target.id
        ),
        "verification_status": verification_status,
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
