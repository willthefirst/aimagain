"""`mount_list` — `GET /<collection>`.

Module name uses a trailing underscore to avoid shadowing the built-in
``list``.
"""

from typing import Any, Awaitable, Callable

from fastapi import Request

from src.framework.dispatch.mounts._common import call_handler_with
from src.framework.dispatch.mounts._spec import QueryParam, ResourceSpec
from src.framework.dispatch.mounts._synth import SynthOptions, synthesize_route_fn
from src.framework.http.responses import APIResponse


def mount_list(
    router: Any,
    spec: ResourceSpec,
    handler: Callable[..., Awaitable[dict]],
    *,
    query_params: tuple[QueryParam, ...] = (),
    public: bool = False,
) -> None:
    """Mount ``GET /<collection>`` rendering ``spec.list_template``.

    The handler's typed signature drives dep wiring: parameters named
    `repo`, `requesting_user`, and any additional repo-typed params
    (resolved via the type registry in
    ``src.framework.dependencies``) are bound automatically. Each
    ``query_params`` entry is added to the route as a FastAPI
    ``Query(...)`` and passed to the handler under its declared name.
    The handler returns a context dict; the mount renders
    ``spec.list_template`` with it.

    ``query_params`` is per-mount because filter shapes are usually
    list-specific (e.g. clinician list takes ``license_type`` and
    ``issuing_state``; users list takes none today). Each ``QueryParam``
    becomes a FastAPI ``Query(...)`` parameter on the route, with full
    OpenAPI doc support and 422-on-invalid validation.

    Polymorphic resources can override the template by returning
    ``template_name`` in the context (the same precedence
    ``mount_form`` uses).

    ``public=True`` overrides ``spec.read_user_dep`` for this mount only —
    used when a resource's list is public but its detail/form pages are
    authenticated (e.g. clinicians). The handler should declare
    ``requesting_user: User | None`` so the synthesis can pass ``None``
    for anonymous viewers.
    """
    if spec.parent is not None:
        raise NotImplementedError(
            "mount_list with spec.parent is not supported yet "
            "(slice 8 / #253). Use mount_related_list for child collections."
        )
    if spec.list_template is None:
        raise ValueError(
            f"mount_list requires {spec.collection!r} to set list_template."
        )
    list_template = spec.list_template

    async def response_builder(*, handler, handler_kwarg_names, kwargs):
        request: Request = kwargs["request"]
        context = await call_handler_with(handler, handler_kwarg_names, kwargs)
        resolved_template = context.pop("template_name", None) or list_template
        return APIResponse.html_response(
            template_name=resolved_template,
            context=context,
            request=request,
            current_user=kwargs.get("requesting_user"),
        )

    user_dep = None if public else spec.read_user_dep
    route_fn = synthesize_route_fn(
        handler=handler,
        spec=spec,
        options=SynthOptions(
            user_dep=user_dep,
            query_params=query_params,
        ),
        response_builder=response_builder,
    )
    router.get("")(route_fn)
