import logging
from typing import Any
from uuid import UUID

from src.domain.logic.providers.repository import ClinicianRepository
from src.domain.logic.users.repository import UserRepository
from src.domain.logic.users.schema import UserActivationUpdate
from src.domain.models import User
from src.domain.specs.user import USER_ENTITY
from src.framework.audit.core import record_audit
from src.framework.audit.repository import AuditRepository
from src.framework.http.exceptions import NotFoundError

logger = logging.getLogger(__name__)


async def user_detail_extras(
    *,
    target: User,
    provider_repo: ClinicianRepository,
    **_: Any,
) -> dict[str, Any]:
    """Per-viewer detail extras for `make_detail_handler(USER_ENTITY)`.

    Fetches the providers the target owns. Viewer-derived flags
    (`is_self`, `can_admin_actions`, `can_view_private`) and the
    `target_user` projection are framework-injected by `handle_detail`
    from `USER_ENTITY.public_fields` / `private_fields` /
    `private_field_predicate` — defense-in-depth (a forgotten template
    guard can re-leak; a missing dict key can't) is preserved.
    """
    return {"providers": await provider_repo.list_for_user(target.id)}


async def handle_set_user_activation(
    user_id: UUID,
    payload: UserActivationUpdate,
    repo: UserRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
) -> User:
    """Admin-only: set a user's activation state. Writes an audit row in the
    same transaction.

    The self-target guard is spec-driven — `USER_ENTITY.state_axis(
    "activation").forbid_self=True` makes the framework wrap this
    handler with the 403 check before invoking it, so this handler is
    free of self-target boilerplate. The route's `current_admin_user`
    dep blocks non-admins.
    """
    target = await repo.get_by_model_id(User, user_id)
    if target is None:
        raise NotFoundError(detail="User not found")

    is_active = payload.state == "active"
    logger.info(
        f"Handler: admin {requesting_user.id} setting activation={payload.state} on user {target.id}"
    )
    activation_axis = USER_ENTITY.state_axis("activation")
    snapshot = activation_axis.audit_snapshot_fn
    before = snapshot(target)
    updated = await repo.patch(target, is_active=is_active)
    await record_audit(
        audit_repo,
        actor_id=requesting_user.id,
        resource_type=USER_ENTITY.audit.type,
        resource_id=updated.id,
        action=activation_axis.action,
        before=before,
        after=snapshot(updated),
    )
    await repo.session.commit()
    return updated
