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

`mutate(...)` is an async context manager that wraps the snapshot-before /
mutate / record_audit / commit ritual. Inside the `async with` body the
caller does the actual mutation; on a clean exit the context manager
captures the post-mutation snapshot, records the audit row, and commits.
On an exception the audit row is not written and no commit fires, so the
transaction rolls back atomically.
"""

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Literal
from uuid import UUID

from pydantic import BaseModel

from src.models import AuditLog, User
from src.repositories.audit_repository import AuditRepository

logger = logging.getLogger(__name__)


def make_snapshotter(
    schema_cls: type[BaseModel],
) -> Callable[[Any], dict[str, Any]]:
    """Build a snapshotter that validates an ORM row through `schema_cls`
    and returns a JSON-mode dict.

    Used by `AuditedResource.snapshot` and by handlers calling
    `record_audit(before=..., after=...)` directly. Centralizes the
    `SchemaCls.model_validate(obj).model_dump(mode="json")` chain so
    audit-row snapshots have one shape across the codebase.
    """

    def _snapshot(obj: Any) -> dict[str, Any]:
        return schema_cls.model_validate(obj).model_dump(mode="json")

    return _snapshot


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
    CREATE_USER = "create_user"
    UPDATE_USER = "update_user"
    DELETE_USER = "delete_user"
    REGISTER = "register"
    CREATE_PROVIDER = "create_provider"
    UPDATE_PROVIDER = "update_provider"
    DELETE_PROVIDER = "delete_provider"
    CREATE_LICENSURE = "create_licensure"
    UPDATE_LICENSURE = "update_licensure"
    DELETE_LICENSURE = "delete_licensure"
    CREATE_EDUCATION = "create_education"
    UPDATE_EDUCATION = "update_education"
    DELETE_EDUCATION = "delete_education"
    CREATE_CERTIFICATION = "create_certification"
    UPDATE_CERTIFICATION = "update_certification"
    DELETE_CERTIFICATION = "delete_certification"
    ADD_FAVORITE = "add_favorite"
    REMOVE_FAVORITE = "remove_favorite"


Verb = Literal["create", "update", "delete"]


@dataclass(frozen=True, slots=True)
class AuditedResource:
    """Declarative bundle for a CRUD-shaped audited resource.

    Module-level constants are the intended use:

        PROVIDER = AuditedResource(
            type="provider",
            snapshot=lambda obj: ProviderAuditSnapshot
                .model_validate(obj).model_dump(mode="json"),
            create=AuditAction.CREATE_PROVIDER,
            update=AuditAction.UPDATE_PROVIDER,
            delete=AuditAction.DELETE_PROVIDER,
        )

    Each handler then calls `record_audit_for(audit_repo, resource=PROVIDER,
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


@asynccontextmanager
async def mutate(
    repo: Any,
    audit_repo: AuditRepository,
    *,
    actor: User,
    target: Any,
    resource: AuditedResource,
    verb: Verb,
):
    """Wrap the snapshot-before / mutate / record_audit / commit ritual.

    Use inside a mutation handler:

        async with mutate(repo, audit_repo, actor=user, target=licensure,
                          resource=LICENSURE, verb="update"):
            await repo.update_licensure(licensure, **payload.model_dump(exclude_unset=True))

    Snapshot timing:
      - `before` is captured before yielding (None for `verb="create"`).
      - `after` is captured after the body returns (None for `verb="delete"`).
      - `target.id` is captured up-front so a delete still has it after
        the row is gone.

    Exceptions raised in the body propagate; the audit row and commit
    are skipped, so the transaction rolls back atomically. This is the
    load-bearing contract: a mutation that raises must not produce an
    audit row, and an audit row must never be durable without its
    matching mutation.
    """
    target_id: UUID = target.id
    before = None if verb == "create" else resource.snapshot(target)
    yield
    after = None if verb == "delete" else resource.snapshot(target)
    await record_audit_for(
        audit_repo,
        resource=resource,
        verb=verb,
        actor_id=actor.id,
        target_id=target_id,
        before=before,
        after=after,
    )
    await repo.session.commit()
    logger.info(
        f"Handler: actor={actor.id} {resource.action_for(verb).value} "
        f"{resource.type}/{target_id}"
    )
