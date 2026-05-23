"""`mount_update` — `PATCH /<collection>/{<id_param>}`."""

from typing import Any, Awaitable, Callable

from fastapi import Request

from src.framework.dispatch.mounts._common import (
    call_handler_with,
    parent_path_param_pairs,
    path_segments_under_router,
)
from src.framework.dispatch.mounts._spec import ResourceSpec
from src.framework.dispatch.mounts._synth import SynthOptions, synthesize_route_fn
from src.framework.http.forms import parse_and_validate_form
from src.framework.http.responses import updated_response


def mount_update(
    router: Any,
    spec: ResourceSpec,
    handler: Callable[..., Awaitable[Any]],
) -> None:
    """Mount ``PATCH /<collection>/{<id_param>}``.

    Parses a form-encoded body via ``spec.update_adapter`` and calls the
    handler with the resource id (under ``spec.id_param``), ``payload=``,
    and any typed deps the handler declares. Handler uses
    ``mutate(verb="update")``.

    Response is ``200 OK`` with body = ``spec.read_to_dict(updated)`` (if
    set, else empty body) and ``HX-Redirect`` =
    ``spec.update_redirect(...)`` (if set, else ``f"/<collection>/<id>"``).

    Requires: ``spec.write_user_dep``, ``spec.update_adapter``.
    ``read_to_dict`` is optional but conventional — clients often want
    the new state without a follow-up GET.
    """
    if spec.write_user_dep is None:
        raise ValueError(
            f"mount_update requires {spec.collection!r} to set write_user_dep."
        )
    if spec.update_adapter is None:
        raise ValueError(
            f"mount_update requires {spec.collection!r} to set update_adapter."
        )

    collection = spec.collection
    id_param = spec.id_param
    update_adapter = spec.update_adapter
    update_redirect = spec.update_redirect
    read_to_dict = spec.read_to_dict

    path = path_segments_under_router(spec, with_id=True)
    parent_id_names = tuple(p[0] for p in parent_path_param_pairs(spec))

    async def response_builder(*, handler, handler_kwarg_names, kwargs):
        request: Request = kwargs["request"]
        kwargs["payload"] = await parse_and_validate_form(request, update_adapter)
        updated = await call_handler_with(handler, handler_kwarg_names, kwargs)
        path_kwargs = {name: kwargs[name] for name in (*parent_id_names, id_param)}
        body = read_to_dict(updated) if read_to_dict else None
        if update_redirect is not None:
            hx = update_redirect(**path_kwargs)
        else:
            hx = f"/{collection}/{updated.id}"
        return updated_response(body=body, hx_redirect=hx)

    route_fn = synthesize_route_fn(
        handler=handler,
        spec=spec,
        options=SynthOptions(
            user_dep=spec.write_user_dep,
            body_adapter=update_adapter,
            path_param_names=(*parent_id_names, id_param),
        ),
        response_builder=response_builder,
    )
    router.patch(path)(route_fn)
