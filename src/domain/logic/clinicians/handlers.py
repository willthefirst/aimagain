"""Clinician-directory orchestration handlers."""

import logging
from typing import Any
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel

from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.favorites.repository import UserFavoriteRepository
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.users.repository import UserRepository
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import (
    Clinician,
    Organization,
    User,
)
from src.framework.authz import assert_fk_ownership, list_visible_to
from src.framework.dispatch.pagination import (
    DEFAULT_PAGE_SIZE,
    Pager,
    base_query,
    offset_for,
    paginate,
    parse_page,
)
from src.framework.http.exceptions import ForbiddenError, NotFoundError
from src.framework.rendering.templating import set_viewer

logger = logging.getLogger(__name__)


async def _assert_clinician_payload_org_ownership(
    *,
    payload: BaseModel,
    requesting_user: User,
    organization_repo: OrganizationRepository,
) -> None:
    """Payload authz for clinician create/update.

    Solo-practice path: when ``payload.solo_practice`` is True,
    auto-create a solo-practice Organization and patch ``payload.org_id``.
    Normal path: delegate to the framework's FK-ownership guard.
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
        child_noun="Clinician",
    )


async def clinician_form_extras(
    *,
    target: Clinician | None,
    requesting_user: User,
    organization_repo: OrganizationRepository,
    **_: Any,
) -> dict[str, Any]:
    return {
        "orgs": await list_visible_to(organization_repo, requesting_user, Organization),
    }


async def clinician_detail_extras(
    *,
    target: Clinician,
    requesting_user: User | None,
    user_favorite_repo: UserFavoriteRepository,
    verification_repo: VerificationRepository,
    **_: Any,
) -> dict[str, Any]:
    latest = await verification_repo.latest_for_clinician(target.id)
    verification_status = latest.status if latest else None
    if requesting_user is None:
        return {"is_favorited": False, "verification_status": verification_status}
    return {
        "is_favorited": await user_favorite_repo.is_favorited(
            user_id=requesting_user.id, clinician_id=target.id
        ),
        "verification_status": verification_status,
    }


async def handle_list_user_clinicians(
    request: Request,
    user_id: UUID,
    repo: ClinicianRepository,
    user_repo: UserRepository,
    requesting_user: User,
) -> dict[str, Any]:
    if user_id != requesting_user.id and not requesting_user.is_superuser:
        raise ForbiddenError(
            detail="Only the target user or an admin may view their clinicians"
        )
    target_user = await user_repo.get_by_model_id(User, user_id)
    if target_user is None:
        raise NotFoundError(detail=f"User {user_id} not found")
    page_number = parse_page(request)
    per_page = DEFAULT_PAGE_SIZE
    clinicians_plus_one = await repo.list_for_user(
        user_id,
        offset=offset_for(page_number, per_page),
        limit=per_page + 1,
    )
    clinicians, page = paginate(
        clinicians_plus_one, page=page_number, per_page=per_page
    )
    set_viewer(requesting_user)
    return {
        "request": request,
        "target_user": target_user,
        "clinicians": clinicians,
        "is_self": user_id == requesting_user.id,
        "current_user": requesting_user,
        "pager": Pager(page=page, base_query=base_query(request)),
    }
