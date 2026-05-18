"""Unified resource-route infrastructure: `ResourceSpec` + opt-in `mount_*`.

A new resource declares a single `ResourceSpec` describing its identity
(collection name, id param, repo, audit bundle, auth deps, schemas,
templates, redirect targets). It then opts into the operations it wants
exposed by calling the corresponding mount function:

    USER_SPEC = ResourceSpec(
        collection="users",
        id_param="user_id",
        repo_dep=get_user_repository,
        audit_resource=USER,
        write_user_dep=current_admin_user,
    )
    mount_delete(router, USER_SPEC, handler=handle_delete_user)

The grammar is **opt-in**: only the mount calls you make produce routes.
A read-only resource simply doesn't call `mount_create`/`mount_update`/
`mount_delete`. A backend-mutated resource (e.g. an async verification
record) still declares an `audit_resource` so backend code can call
`mutate(...)`, but never mounts the mutation routes — HTTP exposure and
backend write capability are independent.

Sub-resources nest under a parent by setting `parent=parent_spec`. The
mount functions walk the chain to build paths like
`/providers/{provider_id}/licensures/{licensure_id}`.

Adding a new mount function (e.g. `mount_list`, `mount_create`) follows
the same pattern: read knobs from the spec, build the route, delegate to
the handler. Each mount is independent — adding one doesn't change the
others. See the per-mount docstrings for the exact handler kwargs each
expects.
"""

import inspect
import types
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Union, get_args, get_origin
from uuid import UUID

from fastapi import Depends, Query, Request, status
from pydantic import BaseModel, TypeAdapter

from src.framework.audit.core import AuditedResource
from src.framework.http.exceptions import ForbiddenError
from src.framework.http.forms import parse_and_validate_form, parse_and_validate_json
from src.framework.http.responses import (
    APIResponse,
    created_response,
    deleted_response,
    updated_response,
)
from src.framework.persistence.dependencies import UnknownRepoTypeError, resolver_for

_UNSET = object()


@dataclass(frozen=True)
class QueryParam:
    """Declarative query-param description for ``mount_list`` / ``mount_form``.

    The mount adds it to the route's ``__signature__`` as a FastAPI
    ``Query(...)`` parameter so OpenAPI docs and 422-on-invalid validation
    work the same way they would on a hand-written route.

    Fields:
      name: kwarg name the mount passes to the handler.
      annotation: type annotation FastAPI uses for parsing/validation
        (``str | None``, ``Literal["a","b"]``, ``int``, etc.).
      default: default value if the param is omitted from the URL.
        Use ``QueryParam.required()`` to mark a param required.
      description: optional OpenAPI description.
    """

    name: str
    annotation: Any
    default: Any = None
    description: str = ""

    @classmethod
    def required(
        cls, name: str, annotation: Any, *, description: str = ""
    ) -> "QueryParam":
        """Mark a query param as required (no default)."""
        return cls(
            name=name, annotation=annotation, default=_UNSET, description=description
        )


@dataclass(frozen=True)
class ResourceSpec:
    """Declarative identity of a resource.

    The mount functions read knobs from here. Most fields default to
    `None` so a spec only declares what its mounted operations actually
    need; e.g. a read-only resource leaves `create_adapter` /
    `update_adapter` / `read_to_dict` unset.

    Fields:
      collection: URL segment (e.g. ``"users"``).
      id_param: name of the path param + handler kwarg for the resource
        id (e.g. ``"user_id"``).
      repo_dep: FastAPI ``Depends`` provider for the resource's primary
        repository. Mount functions inject this and pass it to handlers
        as ``repo=``.
      audit_resource: the ``AuditedResource`` bundle for ``mutate(...)``
        calls. Optional for read-only resources; required if the
        handler does any audited mutation.
      read_user_dep / write_user_dep: ``Depends`` providers for the
        authenticated user on read vs. write routes. ``None`` means
        public (no auth gate). Defaults to ``None`` so callers must
        opt in deliberately — silently public reads would be a bug.
      write_authz: optional callable invoked inside mutation handlers
        to enforce per-resource auth (e.g. ``assert_owner_or_admin``).
        Today the handler calls this itself; reserved on the spec for
        future centralization.
      create_adapter / update_adapter: ``TypeAdapter`` for form-encoded
        request bodies on POST/PATCH. Mount functions parse with
        ``parse_and_validate_form``.
      read_to_dict: callable that turns a persisted object into the
        response body for PATCH (and possibly other mounts later).
      list_template / detail_template / form_template: Jinja paths for
        read mounts. Polymorphic resources (e.g. posts kind-dispatch)
        may return ``template_name`` in the handler's context dict to
        override these per-request.
      (Additional repos beyond ``repo_dep`` are not declared on the
        spec — handlers spell each one out as a typed parameter and
        the mount layer resolves it via the type→resolver registry in
        ``src.framework.dependencies``.)
      create_redirect / update_redirect / delete_redirect: callables
        receiving the path params + (for create/update) the resource id,
        returning the ``HX-Redirect`` URL. ``None`` means use a sensible
        default per mount.
      private_fields: tuple of attribute names that are visible only to
        viewers for whom ``private_field_predicate(actor, target)`` is
        true. Empty tuple means no field-level gating; the resource is
        either fully public or fully gated by the route's auth dep.
        Read by ``src.framework.projections.project_view`` so the
        gating rule can be applied uniformly anywhere a view dict is
        built. Declaring private fields without a predicate raises at
        construction time.
      private_field_predicate: ``Callable[[actor, target], bool]``
        invoked by ``project_view`` to decide whether ``private_fields``
        should appear in the projected view. Required when
        ``private_fields`` is non-empty.
      parent: another ``ResourceSpec`` for sub-resources.
    """

    collection: str
    id_param: str
    repo_dep: Callable[..., Any]
    audit_resource: AuditedResource | None = None

    read_user_dep: Callable[..., Any] | None = None
    write_user_dep: Callable[..., Any] | None = None
    write_authz: Callable[..., None] | None = None

    create_adapter: TypeAdapter | None = None
    update_adapter: TypeAdapter | None = None
    read_to_dict: Callable[[Any], dict] | None = None

    list_template: str | None = None
    detail_template: str | None = None
    form_template: str | None = None

    create_redirect: Callable[..., str] | None = None
    update_redirect: Callable[..., str] | None = None
    delete_redirect: Callable[..., str] | None = None

    private_fields: tuple[str, ...] = ()
    private_field_predicate: Callable[..., bool] | None = None

    parent: "ResourceSpec | None" = None

    def __post_init__(self) -> None:
        # Field-level visibility metadata: `private_fields` names the
        # attributes gated by `private_field_predicate(actor, target)`.
        # Read by `src.framework.projections.project_view` (and any
        # future layer — JSON endpoint, audit snapshot, OpenAPI doc —
        # that needs to know which fields are private). Declaring fields
        # without a predicate would silently leak them, so require both
        # together.
        if self.private_fields and self.private_field_predicate is None:
            raise ValueError(
                f"ResourceSpec({self.collection!r}) declares private_fields="
                f"{self.private_fields!r} but no private_field_predicate — "
                "private fields cannot be gated without a predicate."
            )


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

    path = _path_segments_under_router(spec, with_id=True)
    parent_id_names = tuple(p[0] for p in _parent_path_param_pairs(spec))
    id_param = spec.id_param
    delete_redirect = spec.delete_redirect
    default_redirect = f"/{spec.collection}"

    async def response_builder(*, handler, handler_kwarg_names, kwargs):
        await _call_handler_with(handler, handler_kwarg_names, kwargs)
        path_kwargs = {name: kwargs[name] for name in (*parent_id_names, id_param)}
        if delete_redirect is not None:
            hx_redirect = delete_redirect(**path_kwargs)
        else:
            hx_redirect = default_redirect
        return deleted_response(hx_redirect=hx_redirect)

    route_fn = _synthesize_route_fn(
        handler=handler,
        spec=spec,
        options=_SynthOptions(
            user_dep=spec.write_user_dep,
            path_param_names=(*parent_id_names, id_param),
            inject_request=False,
        ),
        response_builder=response_builder,
    )

    router.delete(path, status_code=status.HTTP_204_NO_CONTENT)(route_fn)


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
    list-specific (e.g. provider list takes ``license_type`` and
    ``issuing_state``; users list takes none today). Each ``QueryParam``
    becomes a FastAPI ``Query(...)`` parameter on the route, with full
    OpenAPI doc support and 422-on-invalid validation.

    Polymorphic resources can override the template by returning
    ``template_name`` in the context (the same precedence
    ``mount_form`` uses).

    ``public=True`` overrides ``spec.read_user_dep`` for this mount only —
    used when a resource's list is public but its detail/form pages are
    authenticated (e.g. providers). The handler should declare
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
        context = await _call_handler_with(handler, handler_kwarg_names, kwargs)
        resolved_template = context.pop("template_name", None) or list_template
        return APIResponse.html_response(
            template_name=resolved_template,
            context=context,
            request=request,
            current_user=kwargs.get("requesting_user"),
        )

    user_dep = None if public else spec.read_user_dep
    route_fn = _synthesize_route_fn(
        handler=handler,
        spec=spec,
        options=_SynthOptions(
            user_dep=user_dep,
            query_params=query_params,
        ),
        response_builder=response_builder,
    )
    router.get("")(route_fn)


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
        context = await _call_handler_with(handler, handler_kwarg_names, kwargs)
        return APIResponse.html_response(
            template_name=detail_template,
            context=context,
            request=request,
            current_user=kwargs.get("requesting_user"),
        )

    route_fn = _synthesize_route_fn(
        handler=handler,
        spec=spec,
        options=_SynthOptions(
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

        alias_route_fn = _synthesize_route_fn(
            handler=handler,
            spec=spec,
            options=_SynthOptions(
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
        context = await _call_handler_with(handler, handler_kwarg_names, kwargs)
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

    route_fn = _synthesize_route_fn(
        handler=handler,
        spec=spec,
        options=_SynthOptions(
            user_dep=spec.read_user_dep,
            query_params=query_params,
            path_param_names=path_param_names,
        ),
        response_builder=response_builder,
    )
    router.get(path)(route_fn)


def mount_create(
    router: Any,
    spec: ResourceSpec,
    handler: Callable[..., Awaitable[Any]],
) -> None:
    """Mount ``POST /<collection>``.

    Parses a form-encoded body via ``spec.create_adapter`` (a Pydantic
    ``TypeAdapter``) and calls the handler with ``payload=``, plus any
    typed deps the handler declares (``repo``, ``audit_repo``,
    ``requesting_user``, any extra repos via the registry). The handler
    is expected to use ``mutate(verb="create")`` so the audit row +
    commit are owned by the context manager.

    Response is ``201 Created`` with ``Location`` and ``HX-Redirect`` set.
    Defaults: ``Location: /<collection>/<new_id>``, ``HX-Redirect`` =
    ``spec.create_redirect(...)`` if set, else ``Location``. The
    ``create_redirect`` callable receives the new id under ``spec.id_param``
    so it can build a per-resource target (e.g. providers redirect to
    ``/providers/{id}/form`` after create).

    Requires: ``spec.write_user_dep``, ``spec.create_adapter``.
    """
    if spec.write_user_dep is None:
        raise ValueError(
            f"mount_create requires {spec.collection!r} to set write_user_dep."
        )
    if spec.create_adapter is None:
        raise ValueError(
            f"mount_create requires {spec.collection!r} to set create_adapter."
        )

    collection = spec.collection
    id_param = spec.id_param
    create_adapter = spec.create_adapter
    create_redirect = spec.create_redirect

    path = _path_segments_under_router(spec, with_id=False)
    parent_id_names = tuple(p[0] for p in _parent_path_param_pairs(spec))

    async def response_builder(*, handler, handler_kwarg_names, kwargs):
        request: Request = kwargs["request"]
        kwargs["payload"] = await parse_and_validate_form(request, create_adapter)
        created = await _call_handler_with(handler, handler_kwarg_names, kwargs)
        path_kwargs = {name: kwargs[name] for name in parent_id_names}
        # Default Location is the canonical resource URL — for a top-level
        # resource that's /<collection>/{id}; for a sub-resource we point
        # at the parent because the spec doesn't have a "list children"
        # canonical URL convention. Per-resource overrides via
        # `create_redirect` handle the HX-Redirect target.
        if spec.parent is None:
            location = f"/{collection}/{created.id}"
        else:
            top = _walk_parent_chain(spec)[0]
            top_id = path_kwargs[top.id_param]
            location = f"/{top.collection}/{top_id}"
        if create_redirect is not None:
            hx = create_redirect(**path_kwargs, **{id_param: created.id})
        else:
            hx = location
        return created_response(id=created.id, location=location, hx_redirect=hx)

    route_fn = _synthesize_route_fn(
        handler=handler,
        spec=spec,
        options=_SynthOptions(
            user_dep=spec.write_user_dep,
            body_adapter=create_adapter,
            path_param_names=parent_id_names,
        ),
        response_builder=response_builder,
    )
    router.post(path, status_code=status.HTTP_201_CREATED)(route_fn)


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

    path = _path_segments_under_router(spec, with_id=True)
    parent_id_names = tuple(p[0] for p in _parent_path_param_pairs(spec))

    async def response_builder(*, handler, handler_kwarg_names, kwargs):
        request: Request = kwargs["request"]
        kwargs["payload"] = await parse_and_validate_form(request, update_adapter)
        updated = await _call_handler_with(handler, handler_kwarg_names, kwargs)
        path_kwargs = {name: kwargs[name] for name in (*parent_id_names, id_param)}
        body = read_to_dict(updated) if read_to_dict else None
        if update_redirect is not None:
            hx = update_redirect(**path_kwargs)
        else:
            hx = f"/{collection}/{updated.id}"
        return updated_response(body=body, hx_redirect=hx)

    route_fn = _synthesize_route_fn(
        handler=handler,
        spec=spec,
        options=_SynthOptions(
            user_dep=spec.write_user_dep,
            body_adapter=update_adapter,
            path_param_names=(*parent_id_names, id_param),
        ),
        response_builder=response_builder,
    )
    router.patch(path)(route_fn)


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
    if spec.parent is not None:
        raise NotImplementedError(
            "mount_state_axis with spec.parent is not supported yet."
        )

    id_param = spec.id_param
    body_adapter = TypeAdapter(body_schema)
    path = f"/{{{id_param}}}/{axis_name}"

    async def response_builder(*, handler, handler_kwarg_names, kwargs):
        request: Request = kwargs["request"]
        kwargs["payload"] = await parse_and_validate_json(request, body_adapter)
        updated = await _call_handler_with(handler, handler_kwarg_names, kwargs)
        body = response_to_dict(updated) if response_to_dict else None
        return updated_response(body=body, hx_refresh=True)

    route_fn = _synthesize_route_fn(
        handler=handler,
        spec=spec,
        options=_SynthOptions(
            user_dep=spec.write_user_dep,
            body_adapter=body_adapter,
            body_format="json",
            path_param_names=(id_param,),
        ),
        response_builder=response_builder,
    )
    router.put(path)(route_fn)


def mount_edge_routes(
    router: Any,
    entity: Any,  # `EntitySpec` for an M:N edge with `relation` set
    *,
    list_handler: Callable[..., Awaitable[dict]],
    add_handler: Callable[..., Awaitable[Any]],
    remove_handler: Callable[..., Awaitable[None]],
) -> None:
    """Mount the three self-only routes for an M:N edge entity.

    Routes:
      - ``GET ""`` → renders ``entity.templates.list`` with the
        context returned by ``list_handler``.
      - ``POST /{<to_attr>}`` → calls ``add_handler`` and returns
        ``201 Created`` (new edge: `Location` + `HX-Redirect` to the
        target's detail page) or ``200 OK`` (idempotent re-add:
        `HX-Refresh: true`). Existence check runs in the helper so
        the wire-shape semantics live in one place.
      - ``DELETE /{<to_attr>}`` → calls ``remove_handler`` and
        returns ``204 No Content`` + `HX-Redirect`. Idempotent —
        the handler is expected to no-op if the edge doesn't exist.

    Reads from the spec:
      - ``entity.relation.to_attr`` — path-param name (e.g.
        ``"provider_id"``).
      - ``entity.relation.to_entity.url_collection`` — used for the
        HX-Redirect target (``"/{to_collection}/{id}"``).
      - ``entity.relation.to_entity.repo_dep`` — Depends for the
        opposite-end repo (e.g. the provider repo on a favorite).
      - ``entity.repo_dep`` — Depends for the edge repo.
      - ``entity.read_user_dep`` — auth dep for the requesting actor.
      - ``entity.templates.list`` — Jinja path for the list page.

    The actor's id is sourced from ``entity.read_user_dep``, not from
    the URL — these routes are self-only (the codebase has no
    parametric ``/users/{user_id}/<collection>/...`` form for edges
    today; admin views of others' edges are not exposed in v1).
    """
    if entity.relation is None:
        raise ValueError(
            f"mount_edge_routes({entity.name!r}): entity has no `relation`; "
            "edge mounts require an M2NRelation declaration on the spec."
        )
    if entity.templates.list is None:
        raise ValueError(
            f"mount_edge_routes({entity.name!r}): entity.templates.list is "
            "required for the list endpoint."
        )
    to_attr = entity.relation.to_attr
    to_entity = entity.relation.to_entity
    to_collection = to_entity.url_collection
    # Handler kwarg name for the opposite-end repo follows the spec
    # name convention: `provider_repo` for the provider entity, etc.
    to_repo_kwarg = f"{to_entity.name}_repo"
    list_template = entity.templates.list
    user_dep = entity.read_user_dep
    repo_dep = entity.repo_dep
    to_repo_dep = to_entity.repo_dep

    # Audit repo isn't on the spec — it's the universal audit-log dep
    # every mutation handler takes. Imported lazily to avoid a cycle
    # with repositories.dependencies (which imports from this module's
    # cluster mate `entity_spec`).
    from src.framework.persistence.dependencies import get_audit_repository

    @router.get("", name=f"{entity.name}:list")
    async def _list_route(  # noqa: F811 — closure, not re-exported
        request: Request,
        user: Any = Depends(user_dep),
        repo: Any = Depends(repo_dep),
    ):
        context = await list_handler(request=request, repo=repo, requesting_user=user)
        return APIResponse.html_response(
            template_name=list_template,
            context=context,
            request=request,
            current_user=user,
        )

    add_route_path = f"/{{{to_attr}}}"

    @router.post(
        add_route_path,
        status_code=status.HTTP_201_CREATED,
        name=f"{entity.name}:add",
    )
    async def _add_route(
        user: Any = Depends(user_dep),
        repo: Any = Depends(repo_dep),
        to_repo: Any = Depends(to_repo_dep),
        audit_repo: Any = Depends(get_audit_repository),
        **path_kwargs: UUID,
    ):
        target_id = path_kwargs[to_attr]
        # Existence-check before delegating so the wire shape can
        # distinguish first-add (201) from idempotent re-add (200 +
        # HX-Refresh). The handler also no-ops on duplicates, so this
        # second query is the cheapest path to keep the wire contract.
        existing = await repo.get_by_pair(user_id=user.id, **{to_attr: target_id})
        edge = await add_handler(
            **{
                to_attr: target_id,
                "repo": repo,
                to_repo_kwarg: to_repo,
                "audit_repo": audit_repo,
                "requesting_user": user,
            }
        )
        redirect = f"/{to_collection}/{target_id}"
        if existing is not None:
            return updated_response(body={"id": str(edge.id)}, hx_refresh=True)
        return created_response(id=edge.id, location=redirect, hx_redirect=redirect)

    # FastAPI's path-param introspection runs against the declared
    # function signature. `**path_kwargs` doesn't expose `provider_id`
    # to FastAPI — fix by attaching an `inspect.Signature` that names
    # the to_attr explicitly. Same trick `_synthesize_route_fn` uses.
    _add_route.__signature__ = _edge_route_signature(  # type: ignore[attr-defined]
        _add_route, to_attr=to_attr
    )

    @router.delete(
        add_route_path,
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"{entity.name}:remove",
    )
    async def _remove_route(
        user: Any = Depends(user_dep),
        repo: Any = Depends(repo_dep),
        audit_repo: Any = Depends(get_audit_repository),
        **path_kwargs: UUID,
    ):
        target_id = path_kwargs[to_attr]
        await remove_handler(
            **{to_attr: target_id},
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=user,
        )
        return deleted_response(hx_redirect=f"/{to_collection}/{target_id}")

    _remove_route.__signature__ = _edge_route_signature(  # type: ignore[attr-defined]
        _remove_route, to_attr=to_attr
    )


def _edge_route_signature(fn: Callable, *, to_attr: str) -> inspect.Signature:
    """Rewrite `fn`'s signature so its `**path_kwargs` becomes an
    explicit typed `to_attr: UUID` parameter that FastAPI binds from
    the URL. The wrapper still receives the value via `**path_kwargs`
    in its body — only the FastAPI-visible signature changes."""
    orig = inspect.signature(fn)
    params: list[inspect.Parameter] = [
        inspect.Parameter(
            to_attr, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=UUID
        )
    ]
    for p in orig.parameters.values():
        if p.kind == inspect.Parameter.VAR_KEYWORD:
            continue
        params.append(p)
    return inspect.Signature(parameters=params)


def mount_related_list(
    router: Any,
    parent_spec: ResourceSpec,
    child_spec: ResourceSpec,
    handler: Callable[..., Awaitable[dict]],
    *,
    template: str,
    singleton_alias: tuple[str, Callable[..., Any]] | None = None,
) -> None:
    """Mount ``GET /<parent.collection>/{<parent.id_param>}/<child.collection>``.

    A scoped read of children belonging to a parent — e.g.
    ``GET /users/{user_id}/providers`` lists the providers owned by a user.

    Handler kwargs: ``request``, the parent id under
    ``parent_spec.id_param`` (e.g. ``user_id=...``), ``repo`` (the
    *child's* repo, since the handler returns children),
    ``requesting_user``, and any typed repos the handler declares
    (resolved via the type registry). Returns a context dict; the
    mount renders ``template``.

    ``template`` is a per-mount kwarg (not on the spec) because related-list
    templates often live in the parent's namespace
    (``users/providers_list.html``, not ``providers/list.html``) — making
    it a per-mount knob keeps both the parent and child specs reusable.

    Auth follows the parent's ``read_user_dep`` (the URL is rooted at the
    parent so its read-auth governs). If the parent is public
    (``read_user_dep=None``), the route is public too.

    ``singleton_alias=("me", current_active_user)`` additionally mounts
    ``GET /<parent.collection>/<alias>/<child.collection>`` (e.g.
    ``/users/me/providers``). The parent id is sourced from
    ``current_active_user().id`` and passed to the handler — same handler,
    same template, same response. The alias is purely an id-derivation
    convenience.
    """
    if not template:
        raise ValueError(
            "mount_related_list requires `template=` — related-list "
            "templates aren't on the spec because they typically live in "
            "the parent's namespace."
        )
    parent_id_param = parent_spec.id_param
    path = f"/{{{parent_id_param}}}/{child_spec.collection}"

    async def response_builder(*, handler, handler_kwarg_names, kwargs):
        request: Request = kwargs["request"]
        context = await _call_handler_with(handler, handler_kwarg_names, kwargs)
        return APIResponse.html_response(
            template_name=template,
            context=context,
            request=request,
            current_user=kwargs.get("requesting_user"),
        )

    # The route renders children, so the synthesis hands the handler the
    # *child's* repo under `repo`. The parent-id path param is bound by
    # name from the URL. Auth follows the *parent's* read user dep.
    route_fn = _synthesize_route_fn(
        handler=handler,
        spec=child_spec,
        options=_SynthOptions(
            user_dep=parent_spec.read_user_dep,
            path_param_names=(parent_id_param,),
        ),
        response_builder=response_builder,
    )

    if singleton_alias is not None:
        alias_segment, session_dep = singleton_alias
        alias_path = f"/{alias_segment}/{child_spec.collection}"

        async def alias_response_builder(*, handler, handler_kwarg_names, kwargs):
            session_user = kwargs["__session_user__"]
            kwargs = {
                **kwargs,
                parent_id_param: session_user.id,
                "requesting_user": session_user,
            }
            return await response_builder(
                handler=handler, handler_kwarg_names=handler_kwarg_names, kwargs=kwargs
            )

        alias_route_fn = _synthesize_route_fn(
            handler=handler,
            spec=child_spec,
            options=_SynthOptions(
                user_dep=None,
                handler_supplied_names=(parent_id_param, "requesting_user"),
                extra_static_deps=(("__session_user__", session_dep),),
            ),
            response_builder=alias_response_builder,
        )
        router.get(alias_path)(alias_route_fn)

    router.get(path)(route_fn)


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
        request: Request = kwargs["request"]
        values: dict[str, Any] = {f.name: kwargs.get(f.name) for f in declared}
        ctx: dict[str, Any] = {
            "request": request,
            "current_user": kwargs.get("requesting_user"),
            "declared_filters": declared,
            "filter_values": values,
            "list_action": list_action,
            "resource_label": entity.url_collection.capitalize(),
        }
        if entity.static_context:
            ctx.update(entity.static_context)
        return ctx

    # `_synthesize_route_fn` reads the handler's signature; build one
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
        from src.domain.models import User

        sig_params.append(
            inspect.Parameter(
                "requesting_user",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=User,
            )
        )
    _search_handler.__signature__ = inspect.Signature(parameters=sig_params)  # type: ignore[attr-defined]
    _search_handler.__name__ = f"_handle_search_{entity.name}"
    _search_handler.__qualname__ = _search_handler.__name__

    async def response_builder(*, handler, handler_kwarg_names, kwargs):
        request: Request = kwargs["request"]
        context = await _call_handler_with(handler, handler_kwarg_names, kwargs)
        return APIResponse.html_response(
            template_name=template,
            context=context,
            request=request,
            current_user=kwargs.get("requesting_user"),
        )

    route_fn = _synthesize_route_fn(
        handler=_search_handler,
        spec=spec,
        options=_SynthOptions(
            user_dep=spec.read_user_dep,
            query_params=tuple(query_params),
        ),
        response_builder=response_builder,
    )
    router.get("/search")(route_fn)


def _normalize_filters(filters: tuple[Any, ...]) -> tuple[QueryParam, ...]:
    """Map each ``EntitySpec.filters`` entry to its ``QueryParam`` shape.

    ``Filter`` instances carry UI metadata on top of the URL contract;
    the mount layer only needs the URL side, so we call
    ``to_query_param()`` on each. Raw ``QueryParam`` entries (the
    legacy shape) pass through unchanged.

    Kept local to this module so ``Filter`` stays an entity_spec-side
    import — the route-mount layer just consumes a uniform tuple.
    """
    from src.framework.dispatch.filters import Filter

    return tuple(f.to_query_param() if isinstance(f, Filter) else f for f in filters)


def _owned_factory_makers() -> dict[str, Callable[..., Callable[..., Awaitable[Any]]]]:
    """Lazy-import the generic CRUD-framework factories for owned subentities.

    Imported on demand to avoid a module-import cycle: this module is
    imported by ``src.framework.entity_spec`` (for ``ResourceSpec`` and
    ``QueryParam``), and ``src.framework.handlers`` imports ``EntitySpec``.
    Doing the import inside ``mount_entity``'s owned-subentity branch
    breaks the cycle — by the time we reach this code at runtime, the
    logic module has finished initializing.

    The factory map below covers every standard CRUD verb plus both
    form verbs; polymorphic ``form_new`` uses the discriminator's
    per-kind ``create_template`` and the spec-injected ``?kind=``
    query param to pick the template at request time.
    """
    from src.framework.dispatch.handlers import (
        make_create_handler,
        make_delete_handler,
        make_detail_handler,
        make_edit_form_handler,
        make_list_handler,
        make_new_form_handler,
        make_update_handler,
    )

    return {
        "create": make_create_handler,
        "update": make_update_handler,
        "delete": make_delete_handler,
        "detail": make_detail_handler,
        "form_edit": make_edit_form_handler,
        "form_new": make_new_form_handler,
        "list": make_list_handler,
    }


_TOP_LEVEL_AUTO_BIND_VERBS = (
    "list",
    "detail",
    "create",
    "update",
    "delete",
    "form_edit",
    "form_new",
)


def _detect_caller_module() -> str:
    """Return `__name__` of the first frame outside this module.

    `mount_entity` is called from a route file like
    `src/domain/routes/<entity>.py`; that's where factory-built handlers
    must be stitched so the contract-test patch path
    `src.domain.routes.<entity>._handle_<verb>_<entity>` resolves. Walks
    up the stack past this module's own frames (and any intermediate
    decorator/wrapper frames inside this module) so the detection is
    robust to internal call chains.
    """
    import inspect

    this_module = __name__
    for frame_info in inspect.stack()[1:]:
        caller = frame_info.frame.f_globals.get("__name__")
        if caller and caller != this_module:
            return caller
    raise RuntimeError(
        "mount_entity could not detect a caller module — every frame "
        "above the call belongs to this module, which shouldn't happen."
    )


def mount_entity(
    router: Any,
    entity: Any,  # `EntitySpec` — imported lazily to avoid a cycle
    *,
    handlers: dict[str, Callable[..., Awaitable[Any]]] | None = None,
    owned_subentities: tuple[Any, ...] = (),
) -> None:
    """Spec-driven dispatcher for an entity's full route surface.

    Reads `entity.routes`, `entity.state_axes`, `entity.subresources`,
    `entity.templates`, `entity.filters`, `entity.discriminator`,
    `entity.singleton_alias`, and the `entity.detail_extras_path` /
    `entity.list_extras_path` extras bindings, and calls the appropriate
    underlying `mount_*` helpers. The existing helpers stay unchanged;
    this is dispatch glue.

    `handlers` maps a verb-or-name to a callable:

      - One per `RouteSet` flag that is `True`: `"list"`, `"detail"`,
        `"create"`, `"update"`, `"delete"`, `"form_new"`, `"form_edit"`.
      - One per `state_axes[i].name` (e.g. `"activation"`).
      - One per `subresources[i].child_spec.collection` (e.g.
        `"providers"` for the user → providers related list).
      - For each `owned_subentities[i]`: one per opted-in verb keyed
        `f"{owned.name}.{verb}"` (e.g. `"provider_licensure.create"`).
        Verbs that match the generic CRUD-framework factories
        (`create`, `update`, `delete`, `detail`, `form_edit`) fall
        back to ``make_<verb>_handler(owned)`` when no explicit key
        is supplied — the common case for subentities whose
        mutations are entirely standard. Supplying the explicit key
        still works and overrides the default.

    Top-level entities get the same factory fallback for their
    standard-CRUD verbs (`detail`, `create`, `update`, `delete`,
    `form_edit`): when `routes.<verb>=True` and the handlers dict
    omits the verb, `mount_entity` builds the handler from
    ``make_<verb>_handler(entity)`` and stitches it onto the route
    file's module so the `_resolve_handler` lookup (and contract-test
    monkey-patches at ``<routes module>._handle_<verb>_<entity>``)
    flow through. The target module is auto-detected from the
    `mount_entity` caller's frame — route files don't pass `module=`.

    Per-viewer / per-list extras (e.g. provider's `is_favorited` flag,
    posts' `post_kinds` list) live on the spec as `detail_extras_path`
    / `list_extras_path` — dotted-string imports resolved lazily at
    mount time (same machinery `StateAxis.handler_path` uses). The
    `detail_extras_repos` / `list_extras_repos` fields declare typed
    repo kwargs the extras callable receives. The pair lives on the
    spec because the late-binding sidesteps the import cycle (handlers
    in `src/logic/<entity>/` import the spec, so the spec can't
    statically import them back).

    Validates loudly at mount time:
      - Every opted-in route / state-axis / subresource must have a
        handler — either explicit in the handlers dict, or via
        factory auto-bind for the standard-CRUD verbs. Missing both
        raises `KeyError`.
      - Extra handler keys not consumed by any spec entry raise
        `ValueError` — catches typos and stale handler bindings the
        spec used to declare.
      - Declaring `detail_extras_path` alongside an explicit
        `handlers["detail"]` (explicit handler would silently win):
        raises at mount time. (Routes-opt-in and repos-without-path
        checks happen at spec construction.)
      - `owned_subentities[i].parent` must equal `entity` (catches a
        passed-in spec from the wrong family).
    """
    spec = entity.to_resource_spec()
    if handlers is None:
        handlers = {}

    # The path/handler pairing is the only check that can't live in
    # `EntitySpec.__post_init__` — `handlers` arrive at the mount call,
    # not at spec construction.
    if entity.detail_extras_path is not None and "detail" in handlers:
        raise ValueError(
            f"mount_entity({entity.name!r}): spec declares "
            "detail_extras_path alongside an explicit "
            "handlers['detail'] — pick one. Extras are for the "
            "factory-built path; an explicit handler owns its own."
        )
    if entity.list_extras_path is not None and "list" in handlers:
        raise ValueError(
            f"mount_entity({entity.name!r}): spec declares "
            "list_extras_path alongside an explicit handlers['list'] "
            "— pick one. Extras are for the factory-built path; an "
            "explicit handler owns its own."
        )
    if entity.form_extras_path is not None and (
        "form_new" in handlers or "form_edit" in handlers
    ):
        raise ValueError(
            f"mount_entity({entity.name!r}): spec declares "
            "form_extras_path alongside an explicit handlers['form_new'] "
            "or handlers['form_edit'] — pick one. Extras are for the "
            "factory-built path; an explicit handler owns its own."
        )
    # `payload_authz_path` is consumed by the factory-built create /
    # update handlers; supplying an explicit `handlers["create"]` /
    # `handlers["update"]` would silently bypass the spec hook.
    if entity.payload_authz_path is not None and "create" in handlers:
        raise ValueError(
            f"mount_entity({entity.name!r}): spec declares "
            "payload_authz_path alongside an explicit handlers['create'] "
            "— pick one. The hook runs in the factory-built path; an "
            "explicit handler would silently bypass it."
        )
    if entity.payload_authz_path is not None and "update" in handlers:
        raise ValueError(
            f"mount_entity({entity.name!r}): spec declares "
            "payload_authz_path alongside an explicit handlers['update'] "
            "— pick one. The hook runs in the factory-built path; an "
            "explicit handler would silently bypass it."
        )

    detail_extras = (
        _resolve_dotted_path(entity, entity.detail_extras_path, "detail_extras_path")
        if entity.detail_extras_path is not None
        else None
    )
    list_extras = (
        _resolve_dotted_path(entity, entity.list_extras_path, "list_extras_path")
        if entity.list_extras_path is not None
        else None
    )
    form_extras = (
        _resolve_dotted_path(entity, entity.form_extras_path, "form_extras_path")
        if entity.form_extras_path is not None
        else None
    )
    payload_authz = (
        _resolve_dotted_path(entity, entity.payload_authz_path, "payload_authz_path")
        if entity.payload_authz_path is not None
        else None
    )

    # Auto-bind top-level CRUD verbs --------------------------------------
    # Same factory-fallback shape as the owned-subentity branch below: any
    # opted-in standard-CRUD verb without an explicit handler is built from
    # `make_<verb>_handler(entity)` and stitched onto the route module so
    # `<routes module>._handle_<verb>_<entity>` is a real attribute. That's
    # the path contract-test monkey-patches use.
    #
    # Explicit handlers (passed via `handlers={...}`) are *also* stitched
    # onto the route module under the same canonical name, with their
    # `__module__` / `__name__` rewritten so `_resolve_handler` reads the
    # current binding from the route module. Without this, contract-test
    # monkey-patches against `<routes module>._handle_<verb>_<entity>`
    # would silently miss explicit handlers.
    import sys

    module = _detect_caller_module()
    factory_makers = _owned_factory_makers()
    mod = sys.modules[module]

    auto_bound: dict[str, Callable[..., Awaitable[Any]]] = {}
    for verb in _TOP_LEVEL_AUTO_BIND_VERBS:
        if not getattr(entity.routes, verb):
            continue
        if verb in handlers:
            continue
        maker = factory_makers[verb]
        if verb == "detail":
            built = maker(
                entity,
                extras=detail_extras,
                extra_repos=entity.detail_extras_repos,
            )
        elif verb == "list":
            built = maker(
                entity,
                extras=list_extras,
                extra_repos=entity.list_extras_repos,
            )
        elif verb in ("form_new", "form_edit"):
            built = maker(
                entity,
                extras=form_extras,
                extra_repos=entity.form_extras_repos,
            )
        elif verb in ("create", "update"):
            built = maker(
                entity,
                payload_authz=payload_authz,
                payload_authz_repos=entity.payload_authz_repos,
            )
        else:
            built = maker(entity)
        built.__module__ = module
        built.__qualname__ = built.__name__
        setattr(mod, built.__name__, built)
        auto_bound[verb] = built

    # Stitch explicit handlers onto the route module under the canonical
    # `_handle_<verb>_<entity>` name. Mutating `__module__` / `__name__`
    # makes `_resolve_handler(fn)` look up the current binding on the
    # route module, so contract-test monkey-patches against the canonical
    # path take effect just like they do for factory-built handlers.
    # The factory shapes name new/edit forms `_handle_get_<name>_new_form` /
    # `_handle_get_<name>_edit_form`; mirror those exactly so the patch
    # path is identical whether the verb is factory-bound or explicit.
    for verb, fn in handlers.items():
        if verb not in _TOP_LEVEL_AUTO_BIND_VERBS:
            continue
        if verb == "form_new":
            canonical_name = f"_handle_get_{entity.name}_new_form"
        elif verb == "form_edit":
            canonical_name = f"_handle_get_{entity.name}_edit_form"
        else:
            canonical_name = f"_handle_{verb}_{entity.name}"
        fn.__module__ = module
        fn.__name__ = canonical_name
        fn.__qualname__ = canonical_name
        setattr(mod, canonical_name, fn)

    # Lookup order: explicit handlers win over auto-bound factories.
    effective_handlers: dict[str, Callable[..., Awaitable[Any]]] = {
        **auto_bound,
        **handlers,
    }

    consumed: set[str] = set()

    # Registration order matters: literal-segment paths (`/form`,
    # `/{id}/form`) must register before the parametric `/{id}` path
    # so FastAPI doesn't try to parse `form` as a UUID. The order
    # below mirrors the route-file ordering each entity used pre-B4.

    if entity.routes.list:
        mount_list(
            router,
            spec,
            handler=effective_handlers["list"],
            query_params=_normalize_filters(entity.filters),
        )
        consumed.add("list")
    if entity.routes.create:
        mount_create(router, spec, handler=effective_handlers["create"])
        consumed.add("create")
    if entity.routes.form_new:
        query_params: tuple[QueryParam, ...] = ()
        if entity.discriminator is not None:
            # Polymorphic entities' create-form `?kind=` query param
            # derives its Literal universe from the discriminator
            # registry — single source of truth for the kind names.
            # Default is `None`, which lets the handler render the
            # picker template (`spec.form_template`) when no kind is
            # specified, rather than silently defaulting to the first
            # registered kind.
            from typing import Literal, Optional

            names = entity.discriminator.names
            query_params = (QueryParam("kind", Optional[Literal[*names]], None),)
        mount_form(
            router,
            spec,
            handler=effective_handlers["form_new"],
            template=entity.templates.form_new,
            query_params=query_params,
        )
        consumed.add("form_new")
    if entity.routes.form_edit:
        mount_form(
            router,
            spec,
            handler=effective_handlers["form_edit"],
            on_existing=True,
            template=entity.templates.form_edit,
        )
        consumed.add("form_edit")
    if entity.routes.search:
        # Literal `/search` registers before the parametric `/{id}` so
        # FastAPI doesn't try to parse "search" as a UUID. The search
        # mount is entity-driven (no handler in the auto-bind set);
        # it just reads `entity.filters` and renders
        # `entity.templates.search`.
        if entity.templates.search is None:
            raise ValueError(
                f"mount_entity({entity.name!r}): routes.search=True but "
                "templates.search is unset — convention is "
                f"`{entity.url_collection}/search.html`."
            )
        mount_search(router, entity, template=entity.templates.search)
    if entity.routes.detail:
        mount_detail(
            router,
            spec,
            handler=effective_handlers["detail"],
            singleton_alias=entity.singleton_alias,
        )
        consumed.add("detail")
    if entity.routes.update:
        mount_update(router, spec, handler=effective_handlers["update"])
        consumed.add("update")
    if entity.routes.delete:
        mount_delete(router, spec, handler=effective_handlers["delete"])
        consumed.add("delete")

    for axis in entity.state_axes:
        handler = _resolve_spec_bound_handler(
            entity, effective_handlers, key=axis.name, handler_path=axis.handler_path
        )
        if axis.forbid_self:
            handler = _wrap_state_axis_with_self_guard(
                handler, id_param=spec.id_param, axis_name=axis.name
            )
        mount_state_axis(
            router,
            spec,
            handler=handler,
            axis_name=axis.name,
            body_schema=axis.body_schema,
            response_to_dict=axis.response_to_dict,
        )
        consumed.add(axis.name)

    for sub in entity.subresources:
        key = sub.child_spec.collection
        handler = _resolve_spec_bound_handler(
            entity, effective_handlers, key=key, handler_path=sub.handler_path
        )
        mount_related_list(
            router,
            parent_spec=spec,
            child_spec=sub.child_spec,
            handler=handler,
            template=sub.template,
            singleton_alias=sub.singleton_alias,
        )
        consumed.add(key)

    # Owned-subentity recursion: each child entity gets its own
    # `mount_entity` call with its own slice of the handlers dict
    # (keyed by `<owned.name>.<verb>`).
    #
    # For verbs whose generic CRUD-framework factory exists
    # (`make_<verb>_handler` in `src.framework.handlers`), we auto-bind a
    # factory-built handler when the explicit key is absent — the
    # default case for credential-style subentities whose mutations
    # are entirely standard. Supplying the explicit key still works
    # and overrides the default; that's the escape hatch for
    # subentities that need bespoke creates / updates / deletes.
    factory_makers = _owned_factory_makers() if owned_subentities else {}
    for owned in owned_subentities:
        if owned.parent is not entity:
            raise ValueError(
                f"mount_entity: owned_subentity {owned.name!r} has "
                f"parent {owned.parent.name if owned.parent else None!r}, "
                f"not {entity.name!r}"
            )
        owned_handlers: dict[str, Callable[..., Awaitable[Any]]] = {}
        for verb in (
            "list",
            "detail",
            "create",
            "update",
            "delete",
            "form_new",
            "form_edit",
        ):
            if not getattr(owned.routes, verb):
                continue
            k = f"{owned.name}.{verb}"
            if k in handlers:
                owned_handlers[verb] = handlers[k]
                consumed.add(k)
            elif verb in factory_makers:
                owned_handlers[verb] = factory_makers[verb](owned)
            else:
                raise KeyError(
                    f"mount_entity({entity.name!r}): owned subentity "
                    f"{owned.name!r} opts into {verb!r} but no handler "
                    f"was supplied at handlers[{k!r}] and no default "
                    "factory exists for this verb."
                )
        mount_entity(router, owned, handlers=owned_handlers)

    # Typo detection — surface stale keys at mount time.
    extras = set(handlers) - consumed
    if extras:
        raise ValueError(
            f"mount_entity({entity.name!r}): handler keys not consumed "
            f"by any spec entry: {sorted(extras)}. Check for typos or "
            "stale bindings."
        )


def _walk_parent_chain(spec: ResourceSpec) -> list[ResourceSpec]:
    """Return ancestors top-to-bottom including ``spec`` itself.

    For a spec with ``parent`` chain ``A → B → C`` (where C is ``spec``),
    returns ``[A, B, C]`` — outermost first.
    """
    chain: list[ResourceSpec] = []
    s: ResourceSpec | None = spec
    while s is not None:
        chain.append(s)
        s = s.parent
    return list(reversed(chain))


def _path_segments_under_router(spec: ResourceSpec, *, with_id: bool) -> str:
    """Build the route path *relative to the router's prefix*.

    The router's prefix is expected to be the topmost ancestor's
    collection (e.g. ``APIRouter(prefix="/providers")`` for both
    provider routes and licensure-under-provider routes). This function
    produces the rest:

    ``/{provider_id}/licensures`` (no id) or
    ``/{provider_id}/licensures/{licensure_id}`` (with id) for a
    licensure spec whose parent is the provider spec.

    For a top-level spec (no parent), returns ``""`` (no id) or
    ``/{spec.id_param}`` (with id).
    """
    chain = _walk_parent_chain(spec)
    # chain[0] is topmost ancestor; its collection is the router prefix.
    # Each subsequent entry contributes /{parent.id_param}/{this.collection}.
    parts: list[str] = []
    for child in chain[1:]:
        assert child.parent is not None
        parts.append(f"/{{{child.parent.id_param}}}/{child.collection}")
    if with_id:
        parts.append(f"/{{{spec.id_param}}}")
    return "".join(parts)


def _parent_path_param_pairs(spec: ResourceSpec) -> tuple[tuple[str, type], ...]:
    """All parent id-params (excluding ``spec.id_param``) the route binds.

    For a licensure spec under provider, returns ``(("provider_id", UUID),)``.
    For a top-level spec, returns ``()``.
    """
    out: list[tuple[str, type]] = []
    s: ResourceSpec | None = spec.parent
    while s is not None:
        out.append((s.id_param, UUID))
        s = s.parent
    out.reverse()
    return tuple(out)


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
        # Resolve through `_resolve_handler` so contract-test monkey-
        # patches against the inner handler's home module take effect
        # — same mechanism `_call_handler_with` uses for the outer
        # handler. Without this, the closure-captured reference would
        # bypass the patch.
        return await _resolve_handler(handler)(*args, **kwargs)

    _self_guard.__wrapped__ = handler  # type: ignore[attr-defined]
    return _self_guard


def _resolve_spec_bound_handler(
    entity: Any,
    effective_handlers: dict[str, Callable[..., Any]],
    *,
    key: str,
    handler_path: str | None,
) -> Callable[..., Any]:
    """Pick the handler for a state-axis or related-list subresource.

    Precedence:

    1. Explicit handler in `mount_entity(handlers=...)` — overrides
       anything declared on the spec (covers tests, hand-rolled cases,
       and entities that haven't been migrated to `handler_path`).
    2. `handler_path` declared on the spec — resolved lazily via
       `importlib.import_module` + `getattr`. Keeps the layer
       direction intact (`specs` never statically imports `logic`).
    3. Neither → raise a clear error naming the entity and the key.
    """
    if key in effective_handlers:
        return effective_handlers[key]
    if handler_path is not None:
        return _resolve_dotted_path(entity, handler_path, key)
    raise KeyError(
        f"mount_entity({entity.name!r}): no handler for {key!r} — "
        f"supply it in `handlers={{{key!r}: ...}}` or set "
        "`handler_path=` on the spec entry."
    )


def _resolve_dotted_path(entity: Any, dotted_path: str, field_label: str) -> Any:
    """Import `pkg.module.attr` lazily and return the attribute.

    Used by `_resolve_spec_bound_handler` (state-axis / subresource
    handler bindings) and by the extras-path resolution in
    `mount_entity`. The shared helper sidesteps the import cycle the
    spec-driven late-binding pattern was built to avoid:
    `specs.<entity>` declares the dotted path as a string,
    and `src.logic.<entity>` (the module that *contains* the attribute)
    is only imported at mount time — long after both modules have
    finished initializing.

    `field_label` is what gets named in errors (e.g. `"activation"` for
    a state-axis handler, `"detail_extras_path"` for the spec field).
    """
    import importlib

    module_path, _, attr = dotted_path.rpartition(".")
    if not module_path:
        raise ValueError(
            f"mount_entity({entity.name!r}): {field_label} "
            f"{dotted_path!r} is not a dotted path "
            "(expected `pkg.module.attr`)."
        )
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ImportError(
            f"mount_entity({entity.name!r}): could not import "
            f"{module_path!r} to resolve {field_label} "
            f"{dotted_path!r}: {exc}"
        ) from exc
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise AttributeError(
            f"mount_entity({entity.name!r}): module "
            f"{module_path!r} has no attribute {attr!r} "
            f"({field_label} {dotted_path!r})."
        ) from exc


def _resolve_handler(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Look up a handler in its home module at call time so test
    monkey-patches applied via ``setattr(<module>, "<name>", mock)`` take
    effect — closure-captured references can't be rebound, but a lookup
    against ``sys.modules`` reads the current binding.

    Falls back to the original reference if anything is missing (e.g. the
    function is a lambda or its module isn't loaded).
    """
    import sys

    mod_name = getattr(fn, "__module__", "")
    fn_name = getattr(fn, "__name__", "")
    if not mod_name or not fn_name:
        return fn
    mod = sys.modules.get(mod_name)
    if mod is None:
        return fn
    return getattr(mod, fn_name, fn)


# --- Signature synthesis -------------------------------------------------
#
# `_synthesize_route_fn` introspects each handler's typed signature and
# pairs every parameter with the right source (path / Depends / Query /
# body parser). The handler's signature becomes the single source of
# truth: forgetting to wire a dep is a registration-time `MountError`,
# not a first-request crash.
#
# Each mount supplies the response shape via `response_builder`. The
# synthesis helper handles the boring middle: introspection, signature
# construction, kwarg routing.


class MountError(TypeError):
    """Raised at mount-registration time when the handler signature is
    incompatible with what the mount can supply. The error names the
    handler, the offending parameter, and (where applicable) the type
    that lacks a registry entry. App startup fails immediately rather
    than the first request 500-ing."""


def _is_optional(annotation: Any) -> tuple[bool, Any]:
    """If `annotation` is `T | None` / `Optional[T]`, return `(True, T)`;
    otherwise `(False, annotation)`. Handles both the 3.10+ pipe syntax
    (`types.UnionType`) and `typing.Union[..., None]`."""
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1 and type(None) in get_args(annotation):
            return True, args[0]
    return False, annotation


def _is_pydantic_model(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


@dataclass(frozen=True)
class _SynthOptions:
    """Per-mount configuration the synthesis helper needs beyond the
    handler signature.

    - `user_dep` resolves `requesting_user`. `None` means the route is
      public (the spec's read user dep was bypassed, e.g. `public=True`
      on `mount_list`).
    - `body_adapter` parses `payload` from the request body when the
      handler takes a `payload` param. `body_format` picks form-encoded
      vs JSON parsing.
    - `query_params` are declarative query params the mount injects.
    - `path_param_names` lists every URL path param the route binds
      (the resource id + any parent ids for sub-resources).
    - `handler_supplied_names` lists handler kwargs that the response
      builder will populate itself before calling the handler (used by
      `singleton_alias` routes that derive the resource id and the
      `requesting_user` from a session dep instead of the URL/auth).
      The synthesis skips these from the FastAPI signature entirely;
      the response builder must fill them via `kwargs[name] = ...`
      before delegating.
    - `extra_static_deps` are additional `Depends(...)` bindings the
      synthesis can't derive from the handler signature (e.g.
      `__session_user__` for alias routes). Keyed by the kwarg name the
      route fn receives; mount-supplied callables consume them inside
      `response_builder`.
    - `inject_request` adds a `request: Request` to the route fn even
      if the handler doesn't take one — needed when the response builder
      reads the request (template rendering uses it for chrome).
    """

    user_dep: Callable[..., Any] | None
    body_adapter: TypeAdapter | None = None
    body_format: str = "form"  # "form" or "json"
    query_params: tuple[QueryParam, ...] = ()
    path_param_names: tuple[str, ...] = ()
    handler_supplied_names: tuple[str, ...] = ()
    extra_static_deps: tuple[tuple[str, Callable[..., Any]], ...] = ()
    inject_request: bool = True


def _synthesize_route_fn(
    *,
    handler: Callable[..., Any],
    spec: ResourceSpec,
    options: _SynthOptions,
    response_builder: Callable[..., Awaitable[Any]],
) -> Callable[..., Any]:
    """Build a FastAPI route function from `handler`'s typed signature.

    Walks the handler's parameters; for each one, decides whether it's
    a path param, a body, a query param, or a `Depends`-injected value
    (repo / user / audit_repo / extra repo via the type registry).
    Builds a wrapper whose `__signature__` is what FastAPI sees;
    delegates response shaping to `response_builder`.

    `response_builder` receives the FULL kwarg dict the wrapper resolves
    (handler kwargs + `request` + any `extra_static_deps`) so each mount
    can pick what it needs to build the response. It is responsible for
    calling the handler (via `_resolve_handler`) and returning the
    Response.

    Raises `MountError` at registration time if the handler signature
    has a parameter the synthesis can't classify.
    """
    handler_sig = inspect.signature(handler)
    path_set = set(options.path_param_names)
    handler_supplied_set = set(options.handler_supplied_names)
    query_names = {qp.name for qp in options.query_params}
    qp_by_name = {qp.name: qp for qp in options.query_params}

    # Names we'll route through to the handler when it's called.
    handler_kwarg_names: list[str] = []
    # Handler kwargs that the synthesis fills with `None` itself (public
    # route + `User | None` requesting_user). The route wrapper merges
    # these into kwargs before calling the handler so the param is
    # present in the call.
    auto_none_handler_kwargs: list[str] = []
    # FastAPI-visible parameter list for the synthesized signature.
    synth_params: list[inspect.Parameter] = []

    # Always inject `request` into the wrapper signature if requested,
    # even when the handler doesn't take one — `response_builder` may
    # still need it for template rendering.
    request_in_handler = "request" in handler_sig.parameters
    if options.inject_request or request_in_handler:
        synth_params.append(
            inspect.Parameter(
                name="request",
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Request,
            )
        )
        if request_in_handler:
            handler_kwarg_names.append("request")

    for param_name, param in handler_sig.parameters.items():
        if param_name == "request":
            continue  # already handled
        # Skip *args / **kwargs — they're not part of the FastAPI-visible
        # contract. The handler may use them for forwarding, but the
        # synthesis only resolves named typed params.
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        annotation = param.annotation
        is_opt, base_ann = _is_optional(annotation)

        # Handler-supplied: the response builder fills this kwarg before
        # calling the handler (e.g. alias routes derive `id_param` and
        # `requesting_user` from a session dep). Skip the FastAPI param
        # entirely; the handler kwarg name is recorded so the wrapper
        # forwards it.
        if param_name in handler_supplied_set:
            handler_kwarg_names.append(param_name)
            continue

        # Path param? The handler asks for it by name; FastAPI binds it
        # from the URL when the route's path string contains it.
        if param_name in path_set:
            synth_params.append(
                inspect.Parameter(
                    name=param_name,
                    kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=UUID,
                )
            )
            handler_kwarg_names.append(param_name)
            continue

        # Query param? Declared on the mount.
        if param_name in query_names:
            qp = qp_by_name[param_name]
            default = (
                Query(..., description=qp.description or None)
                if qp.default is _UNSET
                else Query(qp.default, description=qp.description or None)
            )
            synth_params.append(
                inspect.Parameter(
                    name=param_name,
                    kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=qp.annotation,
                    default=default,
                )
            )
            handler_kwarg_names.append(param_name)
            continue

        # `payload`: parsed from the request body by `response_builder`.
        # No Depends — body parsing happens inside the wrapper because
        # form-encoded bodies need the raw request.
        if param_name == "payload":
            if options.body_adapter is None:
                raise MountError(
                    f"{handler.__qualname__} declares a `payload` parameter "
                    "but the mount did not supply a body adapter. This is a "
                    "mount/spec misconfiguration."
                )
            handler_kwarg_names.append(param_name)
            continue

        # `requesting_user`: the auth-resolved actor. `User | None`
        # means "may be None for anonymous viewers"; require the mount
        # to have a user dep set, OR accept None when `user_dep is None`
        # and the annotation is Optional.
        if param_name == "requesting_user":
            if options.user_dep is None:
                if not is_opt:
                    raise MountError(
                        f"{handler.__qualname__} declares "
                        "`requesting_user: User` but the mount is public "
                        "(no user dep). Either declare the param as "
                        "`User | None` or set a user dep on the spec."
                    )
                # Public route with optional user: pass None directly
                # (no Depends; no FastAPI-visible param). The wrapper
                # fills `kwargs[param_name] = None` before delegating.
                handler_kwarg_names.append(param_name)
                auto_none_handler_kwargs.append(param_name)
                continue
            synth_params.append(
                inspect.Parameter(
                    name=param_name,
                    kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=annotation,
                    default=Depends(options.user_dep),
                )
            )
            handler_kwarg_names.append(param_name)
            continue

        # `repo`: the spec's primary repo. Type is informational only —
        # we don't verify it matches `spec.repo_dep`'s return type
        # because tests intentionally use stub callables that return
        # `SimpleNamespace`. The spec is the source of truth for which
        # resolver to use; the annotation just documents intent.
        if param_name == "repo":
            synth_params.append(
                inspect.Parameter(
                    name=param_name,
                    kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=annotation,
                    default=Depends(spec.repo_dep),
                )
            )
            handler_kwarg_names.append(param_name)
            continue

        # Extra repos: resolve via the type registry. Includes `audit_repo`
        # and any per-handler additional repos (e.g. `user_favorite_repo`
        # on the provider-detail handler).
        if not isinstance(base_ann, type):
            raise MountError(
                f"{handler.__qualname__} parameter {param_name!r} has "
                f"annotation {annotation!r} that is not a class — the "
                "synthesis helper cannot decide how to inject it. Path "
                "params should match the spec's id_param (or a parent's "
                "id_param); query params must be declared in the mount's "
                "`query_params=`."
            )
        try:
            resolver = resolver_for(base_ann)
        except UnknownRepoTypeError as exc:
            raise MountError(
                f"{handler.__qualname__} parameter {param_name!r}: " f"{exc}"
            ) from None
        synth_params.append(
            inspect.Parameter(
                name=param_name,
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=annotation,
                default=Depends(resolver),
            )
        )
        handler_kwarg_names.append(param_name)

    # Extra static deps (alias session dep, etc.) — FastAPI-visible,
    # not passed to the handler unless the wrapper does so explicitly.
    for name, dep in options.extra_static_deps:
        synth_params.append(
            inspect.Parameter(
                name=name,
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Any,
                default=Depends(dep),
            )
        )

    async def _route(**kwargs: Any) -> Any:
        for name in auto_none_handler_kwargs:
            kwargs.setdefault(name, None)
        return await response_builder(
            handler=handler,
            handler_kwarg_names=handler_kwarg_names,
            kwargs=kwargs,
        )

    _route.__signature__ = inspect.Signature(parameters=synth_params)  # type: ignore[attr-defined]
    return _route


async def _call_handler_with(
    handler: Callable[..., Any],
    handler_kwarg_names: list[str],
    kwargs: dict[str, Any],
) -> Any:
    """Call `handler` with the subset of `kwargs` matching the
    introspected handler kwargs. Goes through `_resolve_handler` so
    test monkey-patching against the handler's home module takes effect.
    """
    handler_kwargs = {
        name: kwargs[name] for name in handler_kwarg_names if name in kwargs
    }
    return await _resolve_handler(handler)(**handler_kwargs)
