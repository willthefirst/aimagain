"""`mount_search` — `GET /<collection>/search`."""

import inspect
from typing import Any

from fastapi import Request

from src.framework.dispatch.mounts._common import call_handler_with
from src.framework.dispatch.mounts._spec import QueryParam
from src.framework.dispatch.mounts._synth import SynthOptions, synthesize_route_fn
from src.framework.http.responses import APIResponse


def mount_search(
    router: Any,
    entity: Any,
    *,
    template: str,
) -> None:
    """Mount ``GET /<collection>/search`` rendering the dedicated
    filter page.

    Reads the entity's :class:`Filter` declarations: each one becomes
    a FastAPI ``Query(...)`` param so the search page is pre-populated
    when the toolbar's ``Filter · N`` link forwards the active query
    string.

    No repo, no audit — the handler just returns a context dict with
    the filter declarations and the echoed values; the form's
    ``action`` is the list URL, so submitting *is* the filter
    application.
    """
    from src.framework.dispatch.filters import Filter

    declared = tuple(f for f in entity.filters if isinstance(f, Filter))

    query_params: list[QueryParam] = [f.to_query_param() for f in declared]

    spec = entity.to_resource_spec()
    list_action = f"/{entity.url_collection}"

    async def _search_handler(**kwargs: Any) -> dict[str, Any]:
        from src.framework.rendering.labels import filter_label_for

        request: Request = kwargs["request"]
        values: dict[str, Any] = {f.name: kwargs.get(f.name) for f in declared}
        ctx: dict[str, Any] = {
            "request": request,
            "current_user": kwargs.get("requesting_user"),
            # `entity_name` powers the breadcrumb's `breadcrumb_entity_item`
            # call in `views/search.html` — every view-type template needs
            # it in context to compute the lock-aware collection back link.
            "entity_name": entity.name,
            "declared_filters": declared,
            "filter_values": values,
            "list_action": list_action,
            "resource_label": entity.url_collection.capitalize(),
            # `filter_heading` is the single canonical "Filter <plural>"
            # string the search page H1 and the list-page toolbar's
            # filter link both render — the structural pin that keeps
            # the toolbar button and the page title in sync. See
            # `src/framework/rendering/labels.py`.
            "filter_heading": filter_label_for(entity),
        }
        if entity.static_context:
            ctx.update(entity.static_context)
        return ctx

    # `synthesize_route_fn` reads the handler's signature; build one
    # with the query params declared by name.
    sig_params: list[inspect.Parameter] = [
        inspect.Parameter(
            "request",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=Request,
        )
    ]
    for qp in query_params:
        sig_params.append(
            inspect.Parameter(
                qp.name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=qp.annotation,
            )
        )
    if spec.read_user_dep is not None:
        from src.framework.access.actor.actor import Actor

        sig_params.append(
            inspect.Parameter(
                "requesting_user",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Actor,
            )
        )
    _search_handler.__signature__ = inspect.Signature(parameters=sig_params)  # type: ignore[attr-defined]
    _search_handler.__name__ = f"_handle_search_{entity.name}"
    _search_handler.__qualname__ = _search_handler.__name__

    async def response_builder(*, handler, handler_kwarg_names, kwargs):
        request: Request = kwargs["request"]
        context = await call_handler_with(handler, handler_kwarg_names, kwargs)
        return APIResponse.html_response(
            template_name=template,
            context=context,
            request=request,
            current_user=kwargs.get("requesting_user"),
        )

    route_fn = synthesize_route_fn(
        handler=_search_handler,
        spec=spec,
        options=SynthOptions(
            user_dep=spec.read_user_dep,
            query_params=tuple(query_params),
        ),
        response_builder=response_builder,
    )
    router.get("/search")(route_fn)
