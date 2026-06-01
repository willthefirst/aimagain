"""`mount_list` — `GET /<collection>`.

Module name uses a trailing underscore to avoid shadowing the built-in
``list``. Also owns `handle_list` and `make_list_handler` — the generic
list handler and its factory, originally in `handlers.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable

from fastapi import Request

from src.framework.actor import Actor
from src.framework.authz import is_admin
from src.framework.dispatch.mounts._common import call_handler_with
from src.framework.dispatch.mounts._spec import QueryParam, ResourceSpec
from src.framework.dispatch.mounts._synth import SynthOptions, synthesize_route_fn
from src.framework.dispatch.pagination import (
    DEFAULT_PAGE_SIZE,
    Pager,
    base_query,
    offset_for,
    paginate,
    parse_page,
)
from src.framework.http.responses import APIResponse
from src.framework.persistence.base_repository import BaseRepository
from src.framework.rendering.templating import set_viewer

if TYPE_CHECKING:
    from src.framework.dispatch.entity_spec import EntitySpec
    from src.framework.dispatch.filters import Filter


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


def _active_filter_descriptors(
    declared_filters: tuple[Filter, ...],
    filter_values: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build per-active-value tags for the active-filter strip.

    Each tag is one ``(name, value, label)`` entry — multi-valued
    filters fan out to one tag per selected value. The label is the
    filter's display label paired with the choice's human label when
    available (``"Languages: Spanish"``); free-text filters use the
    raw value.
    """
    out: list[dict[str, Any]] = []
    for f in declared_filters:
        v = filter_values.get(f.name)
        if v is None or v == "" or v == []:
            continue
        choice_labels = (
            dict(f.choices) if getattr(f, "choices", None) else {}  # type: ignore[attr-defined]
        )
        values = v if isinstance(v, list) else [v]
        for one in values:
            human = choice_labels.get(one, str(one))
            out.append(
                {
                    "name": f.name,
                    "value": one,
                    "label": f"{f.display_label}: {human}",
                }
            )
    return out


async def handle_list(
    spec: EntitySpec,
    *,
    request: Request,
    repo: BaseRepository,
    requesting_user: Actor | None,
    filter_values: dict[str, Any],
    extras: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    extra_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generic list handler driven by `spec`; prefers
    ``repo.list_<collection>`` and falls through to ``repo.list_default``
    when the bespoke method doesn't exist.

    Pagination: parses `?page=N` from the request, asks the logic layer
    for `per_page + 1` rows, and slices the probe off to compute
    `has_next` without a separate count query. Per-page size is
    `spec.page_size` if set, otherwise `DEFAULT_PAGE_SIZE`.
    """
    page_number = parse_page(request)
    per_page = spec.page_size or DEFAULT_PAGE_SIZE
    list_kwargs: dict[str, Any] = dict(filter_values)
    # Kind-locked / subset-supertype face — bind `kind` to the face's
    # discriminator. Kind-locked leaves stomp any user value (the URL
    # family is bound to one kind regardless of `?kind=`). Subset faces
    # respect a user-supplied `kind` filter when the spec declares one
    # (intersecting the user's pick with the face's subset); when no
    # user filter is set, fall back to the full subset.
    if spec.discriminator_value is not None:
        list_kwargs[spec.discriminator.column] = spec.discriminator_value
    elif spec.discriminator_values is not None:
        column = spec.discriminator.column
        user_value = list_kwargs.get(column)
        # Normalize user input to a set of kinds. The kind filter on a
        # subset face is conventionally `multi=True` (a `ChoiceFilter`
        # whose choices are the subset). Empty / unset → full subset.
        if user_value:
            if isinstance(user_value, list):
                user_kinds = [k for k in user_value if k in spec.discriminator_values]
            elif user_value in spec.discriminator_values:
                user_kinds = [user_value]
            else:
                user_kinds = []
        else:
            user_kinds = []
        # Empty intersection (user picked only kinds outside the subset,
        # or didn't pick any) → use the full subset. The alternative
        # (return zero rows when user's pick is invalid) is surprising;
        # silently clamping matches kind-locked faces' behavior of
        # ignoring ?kind=other.
        list_kwargs[column] = user_kinds or list(spec.discriminator_values)
    if spec.list_exclude_self and requesting_user is not None:
        list_kwargs["exclude_self"] = requesting_user
    list_kwargs["offset"] = offset_for(page_number, per_page)
    list_kwargs["limit"] = per_page + 1
    list_method = getattr(repo, f"list_{spec.url_collection}", None)
    if list_method is not None:
        items_plus_one = await list_method(**list_kwargs)
    else:
        if spec.list_order_by is None:
            raise ValueError(
                f"handle_list: spec {spec.name!r} has no list_order_by and "
                f"no bespoke list_{spec.url_collection!s} method on the "
                "repo — either declare list_order_by on the spec or add a "
                f"list_{spec.url_collection!s}() method to the repo."
            )
        items_plus_one = await repo.list_default(
            spec.model, order_by=spec.list_order_by, **list_kwargs
        )

    items, page = paginate(items_plus_one, page=page_number, per_page=per_page)
    set_viewer(requesting_user)

    context: dict[str, Any] = {
        "request": request,
        spec.url_collection: items,
        # Shared partials take the URL family name as a macro arg.
        "entity_name": spec.name,
        "resource_label": spec.url_collection.capitalize(),
        "current_user": requesting_user,
        "can_admin_actions": is_admin(requesting_user),
        "pager": Pager(page=page, base_query=base_query(request)),
    }
    # Filter echo — the list page's filter form preselects the active
    # value by reading ``selected_<name>`` from the context. The raw
    # dict is also injected as ``filter_values`` so list templates that
    # render their own inline filter sidebar can read all active values
    # in one place without unpacking each ``selected_*`` variable.
    for fname, fvalue in filter_values.items():
        context[f"selected_{fname}"] = fvalue
    context["filter_values"] = filter_values
    declared = spec.declared_filters
    # `filters` stays for any legacy template still reading it.
    context["filters"] = declared
    # Active filter descriptors — each is `{name, value, label}`. The
    # toolbar's filter link inlines a short summary of these
    # (``Type: Seeking, Description: needle, +2 more filters``); when
    # the list is empty, the link reads ``filters`` instead.
    # Multi-value filters fan out (one descriptor per selected value).
    context["active_filters"] = _active_filter_descriptors(declared, filter_values)
    context["active_filter_count"] = len(context["active_filters"])
    # Search-link URL forwards the current query string so the search
    # page renders its form pre-populated. Only set when the spec opts
    # into `routes.search`.
    if spec.routes.search:
        from urllib.parse import urlencode

        from src.framework.rendering.labels import filter_label_for

        active_pairs: list[tuple[str, str]] = []
        for fname, fvalue in filter_values.items():
            if fvalue is None or fvalue == "" or fvalue == []:
                continue
            if isinstance(fvalue, list):
                for one in fvalue:
                    active_pairs.append((fname, str(one)))
            else:
                active_pairs.append((fname, str(fvalue)))
        qs = urlencode(active_pairs)
        base = f"/{spec.url_collection}/search"
        context["search_url"] = f"{base}?{qs}" if qs else base
        # `filter_heading` is the canonical "Filter <plural>" string the
        # toolbar's filter link reads when no filters are applied, and
        # the search page's H1 reads on its own. Same helper feeds both
        # surfaces — see `src/framework/rendering/labels.py`.
        context["filter_heading"] = filter_label_for(spec)
    else:
        context["search_url"] = None
        context["filter_heading"] = None

    # Spec-declared constants — same merge precedence as handle_detail.
    if spec.static_context:
        context.update(spec.static_context)

    if extras is not None:
        extras_kwargs: dict[str, Any] = {
            "items": items,
            "request": request,
            "requesting_user": requesting_user,
            "filter_values": filter_values,
        }
        if extra_kwargs:
            extras_kwargs.update(extra_kwargs)
        context.update(await extras(**extras_kwargs))

    return context


def make_list_handler(
    spec: EntitySpec,
    *,
    extras: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    extra_repos: tuple[tuple[str, type], ...] = (),
):
    from src.framework.dispatch.handlers import _LIST_SHAPE, _make_factory_handler

    return _make_factory_handler(
        spec, _LIST_SHAPE, handle_list, extras=extras, extra_repos=extra_repos
    )
