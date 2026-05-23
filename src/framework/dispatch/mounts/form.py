"""`mount_form` — `GET /<collection>/form` or `GET /<collection>/{id}/form`."""

from typing import Any, Awaitable, Callable

from fastapi import Request

from src.framework.dispatch.mounts._common import call_handler_with
from src.framework.dispatch.mounts._spec import QueryParam, ResourceSpec
from src.framework.dispatch.mounts._synth import SynthOptions, synthesize_route_fn
from src.framework.http.responses import APIResponse


def mount_form(
    router: Any,
    spec: ResourceSpec,
    handler: Callable[..., Awaitable[dict]],
    *,
    template: str | None = None,
    on_existing: bool = False,
    query_params: tuple[QueryParam, ...] = (),
) -> None:
    """Mount a form-rendering route.

    ``on_existing=False`` mounts ``GET /<collection>/form`` (create-form,
    no entity loaded).
    ``on_existing=True`` mounts ``GET /<collection>/{<id_param>}/form``
    (edit-form, entity loaded by the handler).

    Template precedence (highest to lowest):
      1. ``template_name`` returned in the handler's context dict (for
         polymorphic resources whose template varies at request time —
         e.g. posts kind-dispatch where ``?kind=`` picks the template).
      2. ``template`` kwarg on this call (the simple two-form case where
         create and edit render different static templates).
      3. ``spec.form_template`` (the spec's default).

    Handler kwargs: ``request``, ``repo``, ``requesting_user``, the
    resource id under ``spec.id_param`` (only when ``on_existing=True``),
    each ``query_params`` entry under its declared name, and any
    typed repos the handler declares (resolved via the registry).
    """
    if spec.parent is not None:
        raise NotImplementedError(
            "mount_form with spec.parent is not supported yet (slice 8 / #253)."
        )
    id_param = spec.id_param
    spec_template = spec.form_template

    path = f"/{{{id_param}}}/form" if on_existing else "/form"
    path_param_names = (id_param,) if on_existing else ()

    async def response_builder(*, handler, handler_kwarg_names, kwargs):
        request: Request = kwargs["request"]
        context = await call_handler_with(handler, handler_kwarg_names, kwargs)
        # Resolve template: handler context > per-mount kwarg > spec field.
        # `pop` so the template name doesn't leak into the rendered context.
        resolved_template = (
            context.pop("template_name", None) or template or spec_template
        )
        if resolved_template is None:
            raise RuntimeError(
                f"mount_form for {spec.collection!r} (on_existing={on_existing}) "
                "could not resolve a template — set spec.form_template, "
                "the per-mount `template=` kwarg, or have the handler return "
                "`template_name` in its context."
            )
        return APIResponse.html_response(
            template_name=resolved_template,
            context=context,
            request=request,
            current_user=kwargs.get("requesting_user"),
        )

    route_fn = synthesize_route_fn(
        handler=handler,
        spec=spec,
        options=SynthOptions(
            user_dep=spec.read_user_dep,
            query_params=query_params,
            path_param_names=path_param_names,
        ),
        response_builder=response_builder,
    )
    router.get(path)(route_fn)
