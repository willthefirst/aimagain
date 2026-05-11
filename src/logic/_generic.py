"""Generic framework handlers driven by `EntitySpec`.

Phase 2 of #317 introduces generation: framework code reads from
`EntitySpec` and does the work that today is hand-written per-entity.
This module is the framework's home in the logic layer; the
underscore-prefix filename matches `_authz.py` (shared infrastructure
at the parent tier of `logic/`, importable from every cluster).

B1 (#326) adds `handle_delete` — the smallest verb. Subsequent
B-PRs will add `handle_create`, `handle_update`, etc., each following
the same shape: read knobs from the spec, perform the standard
ritual, delegate non-standard work back to the entity.

Entities with bespoke pre/post-rules keep their custom handlers and
do not call into here. The framework is for the *standard* shape;
custom shapes stay custom.
"""

import inspect
from typing import Any
from uuid import UUID

from src.api.common.entity_spec import EntitySpec
from src.api.common.exceptions import NotFoundError
from src.logic.audit import mutate
from src.models import User
from src.repositories.audit_repository import AuditRepository
from src.repositories.base import BaseRepository


async def handle_delete(
    spec: EntitySpec,
    *,
    target_id: UUID,
    repo: BaseRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
    parent_id: UUID | None = None,
) -> None:
    """Generic delete handler driven by `spec`.

    Performs the standard delete ritual: load target → optional
    parent-FK verification + parent-existence load (owned subentities)
    → write_authz check → audited delete via `mutate(verb="delete")`.

    Reads from the spec:
      - `spec.model` — the SQLAlchemy class used to fetch the target
        (and parent, for owned subentities) via
        `repo.get_by_model_id`.
      - `spec.parent` — if set, the subentity convention is enforced:
        `parent_id` must be supplied, the child's FK column
        (`<parent.name>_id`) must equal `parent_id`, and the parent
        row must exist. `write_authz` runs against the parent (auth
        follows the ownership chain).
      - `spec.write_authz` — invoked against the target (top-level)
        or parent (subentity). `None` skips the check.
      - `spec.audit` — passed to `mutate(...)` as the resource binding.
        Required (delete must be audited).

    Entities with bespoke pre-delete rules (e.g. users' self-guard)
    keep their custom handlers and do not call this function.
    """
    if spec.audit is None:
        raise ValueError(
            f"handle_delete: spec {spec.name!r} has no audit binding; "
            "delete operations must be audited."
        )

    target = await repo.get_by_model_id(spec.model, target_id)
    if target is None:
        raise NotFoundError(detail=f"{spec.name.capitalize()} not found")

    if spec.parent is not None:
        if parent_id is None:
            raise ValueError(
                f"handle_delete: spec {spec.name!r} has parent "
                f"{spec.parent.name!r} but no parent_id was supplied."
            )
        # Subentity convention: the child's FK column is named
        # `<parent.name>_id`. Verify the URL's parent id matches the
        # child's persisted FK — otherwise `/parents/A/children/B`
        # would silently delete a child owned by parent B.
        parent_fk_attr = f"{spec.parent.name}_id"
        if getattr(target, parent_fk_attr) != parent_id:
            raise NotFoundError(detail=f"{spec.name.capitalize()} not found")
        parent = await repo.get_by_model_id(spec.parent.model, parent_id)
        if parent is None:
            raise NotFoundError(detail=f"{spec.parent.name.capitalize()} not found")
        if spec.write_authz is not None:
            spec.write_authz(parent, requesting_user, action=f"delete this {spec.name}")
    else:
        if spec.write_authz is not None:
            spec.write_authz(target, requesting_user, action=f"delete this {spec.name}")

    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=target,
        resource=spec.audit,
        verb="delete",
    ):
        await repo.delete(target)


def make_delete_handler(spec: EntitySpec):
    """Build a `mount_delete`-compatible handler from `spec`.

    The mount layer's signature synthesis (`src/api/common/resource_routes.py`)
    binds URL path params to handler kwargs by name. For the generic
    `handle_delete` to be mountable, the route file needs a callable
    whose signature names the spec's id_param (and the parent's
    id_param for subentities) — generic `**kwargs` wouldn't bind.

    This factory fabricates that signature dynamically and returns a
    wrapper that delegates to `handle_delete(spec, ...)`. Each route
    file does:

        _handle_delete_provider = make_delete_handler(PROVIDER_ENTITY)
        mount_delete(router, PROVIDER_SPEC, handler=_handle_delete_provider)

    The wrapper's `__name__` is `_handle_delete_<spec.name>` so stack
    traces stay readable. The synthesized signature carries typed
    parameters that `mount_delete`'s introspection recognizes: the
    id param (and parent id, if any) as `UUID`, plus `repo`,
    `audit_repo`, `requesting_user` to drive the standard dep
    wiring.
    """
    id_param = spec.id_param
    parent_id_param = spec.parent.id_param if spec.parent is not None else None

    sig_params: list[inspect.Parameter] = []
    if parent_id_param is not None:
        sig_params.append(
            inspect.Parameter(
                parent_id_param,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=UUID,
            )
        )
    sig_params.append(
        inspect.Parameter(
            id_param, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=UUID
        )
    )
    sig_params.append(
        inspect.Parameter(
            "repo",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=BaseRepository,
        )
    )
    sig_params.append(
        inspect.Parameter(
            "audit_repo",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=AuditRepository,
        )
    )
    sig_params.append(
        inspect.Parameter(
            "requesting_user",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=User,
        )
    )

    async def _handler(**kwargs: Any) -> None:
        return await handle_delete(
            spec,
            target_id=kwargs[id_param],
            parent_id=(kwargs[parent_id_param] if parent_id_param else None),
            repo=kwargs["repo"],
            audit_repo=kwargs["audit_repo"],
            requesting_user=kwargs["requesting_user"],
        )

    _handler.__signature__ = inspect.Signature(parameters=sig_params)  # type: ignore[attr-defined]
    _handler.__name__ = f"_handle_delete_{spec.name}"
    _handler.__qualname__ = _handler.__name__
    return _handler
