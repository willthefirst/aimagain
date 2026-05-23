"""`mount_delete` — `DELETE /<collection>/{<id_param>}`."""

from typing import Any, Awaitable, Callable

from fastapi import status

from src.framework.dispatch.mounts._common import (
    call_handler_with,
    parent_path_param_pairs,
    path_segments_under_router,
)
from src.framework.dispatch.mounts._spec import ResourceSpec
from src.framework.dispatch.mounts._synth import SynthOptions, synthesize_route_fn
from src.framework.http.responses import deleted_response


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
    ``/{provider_id}/licensures/{licensure_id}`` for a licensure spec
    whose parent is the provider spec. The handler receives every parent
    id by its id_param name (e.g. ``provider_id=...``) plus the resource's
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
