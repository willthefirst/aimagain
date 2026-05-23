"""`mount_detail` — `GET /<collection>/{<id_param>}`."""

from typing import Any, Awaitable, Callable

from fastapi import Request

from src.framework.dispatch.mounts._common import call_handler_with
from src.framework.dispatch.mounts._spec import ResourceSpec
from src.framework.dispatch.mounts._synth import SynthOptions, synthesize_route_fn
from src.framework.http.responses import APIResponse


def mount_detail(
    router: Any,
    spec: ResourceSpec,
    handler: Callable[..., Awaitable[dict]],
    *,
    singleton_alias: tuple[str, Callable[..., Any]] | None = None,
) -> None:
    """Mount ``GET /<collection>/{<id_param>}`` rendering ``spec.detail_template``.

    The handler's typed signature drives dep wiring: ``request``, the
    resource id under ``spec.id_param``, ``repo``, ``requesting_user``,
    and any extra repos (resolved via the type registry in
    ``src.framework.dependencies``) are bound automatically. The
    handler returns a context dict; the mount renders
    ``spec.detail_template`` with it.

    The multi-repo case (e.g. ``handle_get_user_detail`` takes both a
    user repo and a provider repo) just requires the handler to declare
    each repo as a typed param — the synthesis finds the resolver in
    the registry.

    ``singleton_alias=("me", current_active_user)`` additionally mounts
    ``GET /<collection>/<alias>`` (e.g. ``/users/me``). The id is sourced
    from ``current_active_user().id`` and passed to the handler under
    ``spec.id_param`` — same handler, same template, same response shape.
    The alias is purely an id-derivation convenience.
    """
    if spec.parent is not None:
        raise NotImplementedError(
            "mount_detail with spec.parent is not supported yet (slice 8 / #253)."
        )
    if spec.detail_template is None:
        raise ValueError(
            f"mount_detail requires {spec.collection!r} to set detail_template."
        )
    id_param = spec.id_param
    detail_template = spec.detail_template

    async def response_builder(*, handler, handler_kwarg_names, kwargs):
        request: Request = kwargs["request"]
        context = await call_handler_with(handler, handler_kwarg_names, kwargs)
        return APIResponse.html_response(
            template_name=detail_template,
            context=context,
            request=request,
            current_user=kwargs.get("requesting_user"),
        )

    route_fn = synthesize_route_fn(
        handler=handler,
        spec=spec,
        options=SynthOptions(
            user_dep=spec.read_user_dep,
            path_param_names=(id_param,),
        ),
        response_builder=response_builder,
    )

    if singleton_alias is not None:
        # Register the literal alias path BEFORE the parametric `/{id}` route
        # so FastAPI matches `/users/me` against the alias instead of trying
        # to parse `me` as a UUID against `/users/{user_id}`.
        alias_segment, session_dep = singleton_alias

        async def alias_response_builder(*, handler, handler_kwarg_names, kwargs):
            # Source the resource id from the session-resolved user.
            session_user = kwargs["__session_user__"]
            kwargs = {
                **kwargs,
                id_param: session_user.id,
                "requesting_user": session_user,
            }
            return await response_builder(
                handler=handler, handler_kwarg_names=handler_kwarg_names, kwargs=kwargs
            )

        alias_route_fn = synthesize_route_fn(
            handler=handler,
            spec=spec,
            options=SynthOptions(
                user_dep=None,  # session_dep supplies the user; don't double-inject
                # Tell synthesis that `id_param` and `requesting_user` come
                # from the wrapper, not from the URL or auth dep.
                handler_supplied_names=(id_param, "requesting_user"),
                extra_static_deps=(("__session_user__", session_dep),),
            ),
            response_builder=alias_response_builder,
        )
        router.get(f"/{alias_segment}")(alias_route_fn)

    router.get(f"/{{{id_param}}}")(route_fn)
