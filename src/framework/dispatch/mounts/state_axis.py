"""`mount_state_axis` — `PUT /<collection>/{<id_param>}/<axis_name>`.

Also home to `_wrap_state_axis_with_self_guard`, the framework-side
opt-in that turns `forbid_self=True` on a state axis into a 403 before
the handler runs. The wrapper is referenced by `mount_entity` (sibling
module) and patched by tests, so it stays underscore-prefixed and is
re-exported from `resource_routes.py`.
"""

from typing import Any, Awaitable, Callable

from fastapi import Request
from pydantic import TypeAdapter

from src.framework.dispatch.mounts._common import (
    call_handler_with,
    parent_path_param_pairs,
    path_segments_under_router,
    resolve_handler,
)
from src.framework.dispatch.mounts._spec import ResourceSpec
from src.framework.dispatch.mounts._synth import SynthOptions, synthesize_route_fn
from src.framework.http.exceptions import ForbiddenError
from src.framework.http.forms import parse_and_validate_json
from src.framework.http.responses import updated_response


def mount_state_axis(
    router: Any,
    spec: ResourceSpec,
    handler: Callable[..., Awaitable[Any]],
    *,
    axis_name: str,
    body_schema: type,
    response_to_dict: Callable[[Any], dict] | None = None,
) -> None:
    """Mount ``PUT /<collection>/{<id_param>}/<axis_name>``.

    Implements the state-axis subresource shape from
    ``src/domain/routes/RESOURCE_GRAMMAR.md`` (lines 44-51): a PUT that
    idempotently sets a state value on a resource. Distinct from
    ``mount_update`` (PATCH on the parent for ordinary fields) — the
    response uses ``HX-Refresh: true`` instead of ``HX-Redirect`` because
    the surrounding page renders affordances based on the new state and
    needs to re-fetch in place.

    Parses a JSON body via ``body_schema`` (a Pydantic ``BaseModel``
    subclass) and calls the handler with the resource id under
    ``spec.id_param``, ``payload=`` (the validated body), ``repo=``,
    ``audit_repo=``, and ``requesting_user=``. The handler owns the
    mutation and audit row — state-axis actions like
    ``SET_USER_ACTIVATION`` live outside the
    ``AuditedResource(create, update, delete)`` triple, so they call
    ``record_audit`` directly rather than going through ``mutate()``.
    This mount stays minimum-disruption: it does *not* thread the
    ``AuditAction`` to the handler.

    ``body_schema`` is explicit (not auto-derived from the axis name's
    Literal tuple) because state-axis bodies may carry richer payloads
    than ``{<axis>: <value>}`` for some axes — e.g. a deactivation
    reason or a verified-by id. Single-field bodies still pay one
    declaration to keep the surface uniform.

    **Parent-owned subentities** (``spec.parent is not None``) mount at
    ``/<parent_id_param>/<collection>/<id_param>/<axis_name>`` relative
    to the parent's router prefix — same convention the rest of the
    sub-resource mounts (`mount_create` / `mount_update` /
    `mount_delete`) follow. The handler receives every parent id-param
    as a kwarg alongside ``spec.id_param``. License attestation
    (``LICENSURE_ENTITY`` under ``CLINICIAN_ENTITY``) is the canonical
    consumer: the axis mounts at
    ``PUT /clinicians/{clinician_id}/licensures/{licensure_id}/attestation``
    and the handler receives both ``clinician_id`` and ``licensure_id``.

    Response is ``200 OK`` with body = ``response_to_dict(updated)`` (if
    set, else ``{}``) and ``HX-Refresh: true``. The projection is
    per-mount because each axis surfaces a different field
    (activation → ``is_active``; verification → ``is_verified``).

    Requires: ``spec.write_user_dep``, ``body_schema``.
    """
    if spec.write_user_dep is None:
        raise ValueError(
            f"mount_state_axis requires {spec.collection!r} to set write_user_dep."
        )

    id_param = spec.id_param
    body_adapter = TypeAdapter(body_schema)
    parent_id_names = tuple(p[0] for p in parent_path_param_pairs(spec))
    if spec.parent is None:
        path = f"/{{{id_param}}}/{axis_name}"
    else:
        # `path_segments_under_router(spec, with_id=True)` returns the
        # `/<parent_id>/<collection>/<id_param>` prefix relative to the
        # router (which is rooted at the topmost ancestor's collection,
        # e.g. `/clinicians`). Append the axis name on the end.
        path = f"{path_segments_under_router(spec, with_id=True)}/{axis_name}"

    async def response_builder(*, handler, handler_kwarg_names, kwargs):
        request: Request = kwargs["request"]
        kwargs["payload"] = await parse_and_validate_json(request, body_adapter)
        updated = await call_handler_with(handler, handler_kwarg_names, kwargs)
        body = response_to_dict(updated) if response_to_dict else None
        return updated_response(body=body, hx_refresh=True)

    route_fn = synthesize_route_fn(
        handler=handler,
        spec=spec,
        options=SynthOptions(
            user_dep=spec.write_user_dep,
            body_adapter=body_adapter,
            body_format="json",
            path_param_names=(*parent_id_names, id_param),
        ),
        response_builder=response_builder,
    )
    router.put(path)(route_fn)


def _wrap_state_axis_with_self_guard(
    handler: Callable[..., Awaitable[Any]],
    *,
    id_param: str,
    axis_name: str,
) -> Callable[..., Awaitable[Any]]:
    """Wrap a state-axis handler so the framework rejects self-target
    invocations with 403 before invoking the entity's mutation logic.

    The comparison is `kwargs[id_param] == requesting_user.id`, which
    only matches on user-shaped entities (where the URL's target id IS
    a user id). For owned resources, target_id is a row UUID, so the
    comparison is a no-op — the flag's documented scope.

    The wrapper preserves the handler's signature via `__wrapped__` so
    `inspect.signature` (used by `_synthesize_route_fn`) still sees the
    real parameters.
    """

    async def _self_guard(*args: Any, **kwargs: Any) -> Any:
        target_id = kwargs.get(id_param)
        requesting_user = kwargs.get("requesting_user")
        if (
            target_id is not None
            and requesting_user is not None
            and target_id == requesting_user.id
        ):
            raise ForbiddenError(
                detail=f"Cannot change your own {axis_name} via this endpoint"
            )
        # Resolve through `resolve_handler` so contract-test monkey-
        # patches against the inner handler's home module take effect
        # — same mechanism `call_handler_with` uses for the outer
        # handler. Without this, the closure-captured reference would
        # bypass the patch.
        return await resolve_handler(handler)(*args, **kwargs)

    _self_guard.__wrapped__ = handler  # type: ignore[attr-defined]
    return _self_guard
