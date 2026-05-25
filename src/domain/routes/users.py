from fastapi import Depends
from fastapi.responses import RedirectResponse

from src.auth_config import current_active_user
from src.domain.logic.users.handlers import handle_set_onboarding_intent
from src.domain.logic.users.repository import UserRepository, get_user_repository
from src.domain.logic.users.schema import OnboardingIntentUpdate
from src.domain.models import User
from src.domain.specs.user import USER_ENTITY
from src.framework import register_entity
from src.framework.audit.repository import AuditRepository
from src.framework.dispatch.resource_routes import mount_entity
from src.framework.persistence.dependencies import get_audit_repository

router = register_entity(USER_ENTITY)


# Every verb is factory-built or spec-resolved:
#   - list / detail / delete — auto-bound from `make_<verb>_handler(USER_ENTITY)`.
#     `delete` honors `USER_ENTITY.delete_forbid_self=True` for the
#     "admin can't delete self" rule.
#   - activation — state-axis handler resolved via the spec's
#     `handler_path`; the framework wraps it with the `forbid_self`
#     self-target guard declared on the axis.
#   - providers — related-list subresource, same `handler_path` path.
# Detail extras (`user_detail_extras` + the provider repo it needs)
# live on the spec via `detail_extras_path`.
mount_entity(router, USER_ENTITY)


@router.put(
    "/me/onboarding-intent",
    tags=["users"],
    name="users:set_onboarding_intent",
)
async def put_onboarding_intent(
    payload: OnboardingIntentUpdate,
    requesting_user: User = Depends(current_active_user),
    repo: UserRepository = Depends(get_user_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
):
    """Set the current user's onboarding intent.

    Self-only: always operates on the authenticated user. Writes an
    audit row with action `UPDATE_USER_ONBOARDING_INTENT`. On success,
    redirects to `/openings` (placeholder; T2 will change to `/welcome`).

    This is a field-cluster subresource (RESOURCE_GRAMMAR.md §2) — a
    single-value PUT because `onboarding_intent` has different rules
    than ordinary PATCH fields (dedicated audit action, session sync).
    """
    await handle_set_onboarding_intent(
        payload=payload,
        repo=repo,
        audit_repo=audit_repo,
        requesting_user=requesting_user,
    )
    return RedirectResponse(url="/openings", status_code=302)
