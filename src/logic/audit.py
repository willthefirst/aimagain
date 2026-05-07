"""Audit-log helper for mutation handlers.

Wraps `AuditRepository.record(...)` with the calling convention used by the
handlers in `src/logic/`. Handlers call this once per mutation, **inside the
same transaction** as the mutation itself — the discipline in
`RESOURCE_GRAMMAR.md:135` requires the audit row to be durable iff the
mutation is. The handler still owns the commit.

`actor_id` is `None` for unauthenticated mutations (e.g. self-signup); the
schema permits it.

`AuditAction` is the closed vocabulary of mutation kinds. Add a member here
when wiring `record_audit` into a new mutation handler; never reuse an
existing value for a different semantic — values are persisted forever and
existing rows depend on the meaning being stable.

`AuditedResource` bundles the three things that always vary together for a
CRUD-shaped resource: the persisted `resource_type` string, the
create/update/delete `AuditAction` triple, and the snapshotter that builds
the row's `before`/`after` JSON. Declare one per audited resource alongside
your `handle_*` definitions and call `record_audit_for(...)` instead of
re-typing the three constants at every callsite. Non-CRUD audits (register,
set-activation, etc.) keep using `record_audit(...)` directly.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Literal
from uuid import UUID

from src.models import AuditLog
from src.repositories.audit_repository import AuditRepository

logger = logging.getLogger(__name__)


class AuditAction(str, Enum):
    """Closed vocabulary of mutation actions recorded in the audit log.

    Inherits from `str` so values serialize transparently into the
    `audit_log.action` column and equality comparisons against raw strings
    keep working (`AuditAction.CREATE_POST == "create_post"` is True).
    """

    CREATE_POST = "create_post"
    UPDATE_POST = "update_post"
    DELETE_POST = "delete_post"
    SET_USER_ACTIVATION = "set_user_activation"
    DELETE_USER = "delete_user"
    REGISTER = "register"
    CREATE_PROVIDER_PROFILE = "create_provider_profile"
    UPDATE_PROVIDER_PROFILE = "update_provider_profile"
    DELETE_PROVIDER_PROFILE = "delete_provider_profile"
    CREATE_LICENSURE = "create_licensure"
    UPDATE_LICENSURE = "update_licensure"
    DELETE_LICENSURE = "delete_licensure"
    CREATE_EDUCATION = "create_education"
    UPDATE_EDUCATION = "update_education"
    DELETE_EDUCATION = "delete_education"
    CREATE_CERTIFICATION = "create_certification"
    UPDATE_CERTIFICATION = "update_certification"
    DELETE_CERTIFICATION = "delete_certification"


Verb = Literal["create", "update", "delete"]


@dataclass(frozen=True, slots=True)
class AuditedResource:
    """Declarative bundle for a CRUD-shaped audited resource.

    Module-level constants are the intended use:

        PROFILE = AuditedResource(
            type="provider_profile",
            snapshot=lambda obj: ProviderProfileAuditSnapshot
                .model_validate(obj).model_dump(mode="json"),
            create=AuditAction.CREATE_PROVIDER_PROFILE,
            update=AuditAction.UPDATE_PROVIDER_PROFILE,
            delete=AuditAction.DELETE_PROVIDER_PROFILE,
        )

    Each handler then calls `record_audit_for(audit_repo, resource=PROFILE,
    verb="update", ...)` instead of typing `resource_type=`, `action=`, and
    a per-resource `_snapshot_X` wrapper at every callsite.

    `AuditAction` membership is intentionally *not* derived from this dataclass:
    enum values are persisted forever and must stay explicit.
    """

    type: str
    snapshot: Callable[[Any], dict[str, Any]]
    create: AuditAction
    update: AuditAction
    delete: AuditAction

    def action_for(self, verb: Verb) -> AuditAction:
        return getattr(self, verb)


async def record_audit(
    audit_repo: AuditRepository,
    *,
    actor_id: UUID | None,
    resource_type: str,
    resource_id: UUID,
    action: AuditAction,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    """Record a single audit row. Returns the persisted row (flushed, not committed)."""
    row = await audit_repo.record(
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        before=before,
        after=after,
    )
    logger.info(f"Audit: actor={actor_id} {action.value} {resource_type}/{resource_id}")
    return row


async def record_audit_for(
    audit_repo: AuditRepository,
    *,
    resource: AuditedResource,
    verb: Verb,
    actor_id: UUID | None,
    target_id: UUID,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    """Record an audit row for `resource` + `verb`, deriving `resource_type`
    and `action` from the `AuditedResource` declaration. The caller still
    supplies the snapshots and the actor."""
    return await record_audit(
        audit_repo,
        actor_id=actor_id,
        resource_type=resource.type,
        resource_id=target_id,
        action=resource.action_for(verb),
        before=before,
        after=after,
    )
