"""`mount_delete` — `DELETE /<collection>/{<id_param>}`.

Also owns `handle_delete` and `make_delete_handler` — the generic
delete handler and its factory, originally in `handlers.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable
from uuid import UUID

from fastapi import status

from src.framework.actor import Actor
from src.framework.audit.core import mutate
from src.framework.audit.repository import AuditRepository
from src.framework.dispatch.mounts._common import (
    assert_kind_lock,
    call_handler_with,
    parent_path_param_pairs,
    path_segments_under_router,
)
from src.framework.dispatch.mounts._spec import ResourceSpec
from src.framework.dispatch.mounts._synth import SynthOptions, synthesize_route_fn
from src.framework.http.exceptions import ForbiddenError, NotFoundError
from src.framework.http.responses import deleted_response
from src.framework.persistence.base_repository import BaseRepository

if TYPE_CHECKING:
    from src.framework.dispatch.entity_spec import EntitySpec


def mount_delete(
    router: Any,
    spec: ResourceSpec,
    handler: Callable[..., Awaitable[None]],
) -> None:
    """Mount ``DELETE /<collection>/{<id_param>}`` on ``router``.

    The handler's typed signature drives dep wiring: parameters named
    `repo`, `audit_repo`, `requesting_user`, and the resource id (under
    ``spec.id_param``, plus any parent ids for sub-resources) are bound
    automatically. The handler is expected to use ``mutate(verb="delete")``
    so the audit row is written and the transaction commits inside the
    same scope.

    Response is ``204 No Content`` with ``HX-Redirect`` set by
    ``spec.delete_redirect(**path_params)`` if provided, else
    ``f"/{spec.collection}"``.

    Sub-resources nest via ``spec.parent``. The router's prefix is the
    topmost ancestor's collection; the mount produces a path like
    ``/{clinician_id}/licensures/{licensure_id}`` for a licensure spec
    whose parent is the clinician spec. The handler receives every parent
    id by its id_param name (e.g. ``clinician_id=...``) plus the resource's
    own id (``licensure_id=...``).
    """
    if spec.write_user_dep is None:
        raise ValueError(
            f"mount_delete requires {spec.collection!r} to set "
            "write_user_dep — silent public deletes would be a bug."
        )

    path = path_segments_under_router(spec, with_id=True)
    parent_id_names = tuple(p[0] for p in parent_path_param_pairs(spec))
    id_param = spec.id_param
    delete_redirect = spec.delete_redirect
    default_redirect = f"/{spec.collection}"

    async def response_builder(*, handler, handler_kwarg_names, kwargs):
        await call_handler_with(handler, handler_kwarg_names, kwargs)
        path_kwargs = {name: kwargs[name] for name in (*parent_id_names, id_param)}
        if delete_redirect is not None:
            hx_redirect = delete_redirect(**path_kwargs)
        else:
            hx_redirect = default_redirect
        return deleted_response(hx_redirect=hx_redirect)

    route_fn = synthesize_route_fn(
        handler=handler,
        spec=spec,
        options=SynthOptions(
            user_dep=spec.write_user_dep,
            path_param_names=(*parent_id_names, id_param),
            inject_request=False,
        ),
        response_builder=response_builder,
    )

    router.delete(path, status_code=status.HTTP_204_NO_CONTENT)(route_fn)


async def handle_delete(
    spec: EntitySpec,
    *,
    target_id: UUID,
    repo: BaseRepository,
    audit_repo: AuditRepository,
    requesting_user: Actor,
    parent_id: UUID | None = None,
) -> None:
    """Generic delete handler driven by `spec`."""
    if spec.audit is None:
        raise ValueError(
            f"handle_delete: spec {spec.name!r} has no audit binding; "
            "delete operations must be audited."
        )

    target = await repo.get_by_model_id(spec.model, target_id)
    if target is None:
        raise NotFoundError(detail=f"{spec.name.capitalize()} not found")
    assert_kind_lock(spec, target)

    # Self-target guard for user-shaped entities — the comparison only
    # matches when `target.id` IS the requesting user's id (i.e. the row
    # is a user). For owned resources, target.id is a row UUID, so the
    # comparison is harmless. See `EntitySpec.delete_forbid_self`.
    if spec.delete_forbid_self and target.id == requesting_user.id:
        raise ForbiddenError(
            detail=f"Cannot delete your own {spec.name} via this endpoint"
        )

    if spec.parent is not None:
        if parent_id is None:
            raise ValueError(
                f"handle_delete: spec {spec.name!r} has parent "
                f"{spec.parent.name!r} but no parent_id was supplied."
            )
        parent = await repo.get_by_model_id(spec.parent.model, parent_id)
        if parent is None:
            raise NotFoundError(detail=f"{spec.parent.name.capitalize()} not found")
        # Verify the URL's parent id matches the child's logical parent —
        # otherwise `/parents/A/children/B` would silently mutate a child
        # owned by parent B. Default convention: child holds `<parent.name>_id`
        # equal to `parent.id`. Specs with a shared non-parent FK
        # (e.g. clinician credentials FK to `clinicians.id`) override via
        # `child_parent_match_attr`.
        if spec.child_parent_match_attr is not None:
            attr = spec.child_parent_match_attr
            if getattr(target, attr) != getattr(parent, attr):
                raise NotFoundError(detail=f"{spec.name.capitalize()} not found")
        else:
            parent_fk_attr = spec.parent_fk_attr or f"{spec.parent.name}_id"
            if getattr(target, parent_fk_attr) != parent_id:
                raise NotFoundError(detail=f"{spec.name.capitalize()} not found")
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
    from src.framework.dispatch.mounts._factory import (
        _DELETE_SHAPE,
        _make_factory_handler,
    )

    return _make_factory_handler(spec, _DELETE_SHAPE, handle_delete)
