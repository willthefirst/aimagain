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
`/providers/{provider_id}/licensures/{licensure_id}`. Parent-chain
support lands incrementally; until slice 8 (#253) only `mount_delete`
exists, and it asserts `parent is None` so callers don't silently fall
into an unsupported case.

Adding a new mount function (e.g. `mount_list`, `mount_create`) follows
the same pattern: read knobs from the spec, build the route, delegate to
the handler. Each mount is independent — adding one doesn't change the
others. See the per-mount docstrings for the exact handler kwargs each
expects.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import UUID

from fastapi import Depends, Request, status
from pydantic import TypeAdapter

from src.api.common.forms import parse_and_validate_form
from src.api.common.responses import (
    APIResponse,
    created_response,
    deleted_response,
    updated_response,
)
from src.logic.audit import AuditedResource


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
      (Per-mount ``extra_repo_deps`` kwargs let an individual mount
        inject additional repos beyond ``repo_dep`` for handlers that
        need them — e.g. ``handle_get_user_detail`` takes the provider
        repo. They're per-mount, not per-spec, because different mounts
        on the same spec may need different extras.)
      create_redirect / update_redirect / delete_redirect: callables
        receiving the path params + (for create/update) the resource id,
        returning the ``HX-Redirect`` URL. ``None`` means use a sensible
        default per mount.
      parent: another ``ResourceSpec`` for sub-resources. Slice 8 (#253)
        wires this through; until then ``mount_delete`` asserts
        ``parent is None``.
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

    parent: "ResourceSpec | None" = None


def mount_delete(
    router: Any,
    spec: ResourceSpec,
    handler: Callable[..., Awaitable[None]],
    *,
    audit_repo_dep: Callable[..., Any],
) -> None:
    """Mount ``DELETE /<collection>/{<id_param>}`` on ``router``.

    The handler is invoked with the resource id (under ``spec.id_param``),
    ``repo`` (from ``spec.repo_dep``), ``audit_repo`` (from
    ``audit_repo_dep``), and ``requesting_user`` (from
    ``spec.write_user_dep``). The handler is expected to use
    ``mutate(verb="delete")`` so the audit row is written and the
    transaction commits inside the same scope.

    Response is ``204 No Content`` with ``HX-Redirect`` set by
    ``spec.delete_redirect(**path_params)`` if provided, else
    ``f"/{spec.collection}"``.

    `audit_repo_dep` is passed in rather than read from the spec because
    the audit repo dependency is a layer-wide concern, not a per-resource
    knob — every mounted mutation uses the same one. Callers import it
    once and reuse it across all `mount_*` calls.

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
    parent_path_params = _parent_path_param_pairs(spec)
    id_param = spec.id_param
    delete_redirect = spec.delete_redirect
    default_redirect = f"/{spec.collection}"

    async def _delete(**kwargs: Any) -> Any:
        path_kwargs = _kwargs_for_handler_path(spec, kwargs, with_id=True)
        await _resolve_handler(handler)(
            **path_kwargs,
            repo=kwargs["repo"],
            audit_repo=kwargs["audit_repo"],
            requesting_user=kwargs["requesting_user"],
        )
        if delete_redirect is not None:
            hx_redirect = delete_redirect(**path_kwargs)
        else:
            hx_redirect = default_redirect
        return deleted_response(hx_redirect=hx_redirect)

    _set_route_signature(
        _delete,
        path_params=(*parent_path_params, (id_param, UUID)),
        deps=(
            ("repo", spec.repo_dep),
            ("audit_repo", audit_repo_dep),
            ("requesting_user", spec.write_user_dep),
        ),
    )

    router.delete(path, status_code=status.HTTP_204_NO_CONTENT)(_delete)


def mount_list(
    router: Any,
    spec: ResourceSpec,
    handler: Callable[..., Awaitable[dict]],
    *,
    extra_repo_deps: tuple[Callable[..., Any], ...] = (),
) -> None:
    """Mount ``GET /<collection>`` rendering ``spec.list_template``.

    The handler is invoked with ``request``, ``repo`` (from
    ``spec.repo_dep``), ``requesting_user`` (from ``spec.read_user_dep``,
    or ``None`` if no auth gate is set), and any ``extra_repo_deps`` under
    their dep callable's name (``get_<entity>_repository`` →
    ``<entity>_repo``). The handler returns a context dict; the mount
    renders ``spec.list_template`` with it.

    ``extra_repo_deps`` is per-mount, not per-spec, because different
    mounts on the same resource often need different extra repos (e.g.
    list doesn't need provider_repo but detail does).

    Polymorphic resources can override the template by returning
    ``template_name`` in the context — slice 5 (#250) wires that through
    for ``mount_form``; for now ``mount_list`` always uses
    ``spec.list_template``.

    Until slice 8 (#253), ``spec.parent`` must be ``None`` here; nested
    list routes use ``mount_related_list`` (slice 9 / #254).
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
    extra_deps_named = _name_extra_repo_deps(extra_repo_deps)

    async def _list(**kwargs: Any) -> Any:
        request: Request = kwargs["request"]
        context = await _resolve_handler(handler)(
            request=request,
            repo=kwargs["repo"],
            requesting_user=kwargs.get("requesting_user"),
            **{name: kwargs[name] for name, _ in extra_deps_named},
        )
        return APIResponse.html_response(
            template_name=list_template, context=context, request=request
        )

    _set_route_signature(
        _list,
        path_params=(("request", Request),),
        deps=_read_route_deps(spec, extra_deps_named),
    )
    router.get("")(_list)


def mount_detail(
    router: Any,
    spec: ResourceSpec,
    handler: Callable[..., Awaitable[dict]],
    *,
    extra_repo_deps: tuple[Callable[..., Any], ...] = (),
) -> None:
    """Mount ``GET /<collection>/{<id_param>}`` rendering ``spec.detail_template``.

    The handler is invoked with ``request``, the resource id under
    ``spec.id_param``, ``repo``, ``requesting_user``, and any
    ``extra_repo_deps`` under their derived kwarg name. Returns a
    context dict; the mount renders ``spec.detail_template`` with it.

    The multi-repo case (e.g. ``handle_get_user_detail`` takes both a
    user repo and a provider repo) is the canonical reason
    ``extra_repo_deps`` exists.
    """
    if spec.parent is not None:
        raise NotImplementedError(
            "mount_detail with spec.parent is not supported yet " "(slice 8 / #253)."
        )
    if spec.detail_template is None:
        raise ValueError(
            f"mount_detail requires {spec.collection!r} to set detail_template."
        )
    id_param = spec.id_param
    detail_template = spec.detail_template
    extra_deps_named = _name_extra_repo_deps(extra_repo_deps)

    async def _detail(**kwargs: Any) -> Any:
        request: Request = kwargs["request"]
        resource_id: UUID = kwargs[id_param]
        context = await _resolve_handler(handler)(
            request=request,
            repo=kwargs["repo"],
            requesting_user=kwargs.get("requesting_user"),
            **{id_param: resource_id},
            **{name: kwargs[name] for name, _ in extra_deps_named},
        )
        return APIResponse.html_response(
            template_name=detail_template, context=context, request=request
        )

    _set_route_signature(
        _detail,
        path_params=(("request", Request), (id_param, UUID)),
        deps=_read_route_deps(spec, extra_deps_named),
    )
    router.get(f"/{{{id_param}}}")(_detail)


def mount_form(
    router: Any,
    spec: ResourceSpec,
    handler: Callable[..., Awaitable[dict]],
    *,
    template: str | None = None,
    on_existing: bool = False,
    extra_repo_deps: tuple[Callable[..., Any], ...] = (),
) -> None:
    """Mount a form-rendering route.

    ``on_existing=False`` mounts ``GET /<collection>/form`` (create-form,
    no entity loaded).
    ``on_existing=True`` mounts ``GET /<collection>/{<id_param>}/form``
    (edit-form, entity loaded by the handler).

    Template precedence (highest to lowest):
      1. ``template_name`` returned in the handler's context dict (for
         polymorphic resources whose template varies at request time —
         e.g. posts kind-dispatch).
      2. ``template`` kwarg on this call (the simple two-form case where
         create and edit render different static templates).
      3. ``spec.form_template`` (the spec's default).

    Handler kwargs: ``request``, ``repo``, ``requesting_user``, the
    resource id under ``spec.id_param`` (only when ``on_existing=True``),
    and any ``extra_repo_deps``. Pure create-form handlers that don't
    use the repo still have to accept ``repo=`` (just ignore it) —
    uniform mount-handler contract beats a special case.
    """
    if spec.parent is not None:
        raise NotImplementedError(
            "mount_form with spec.parent is not supported yet (slice 8 / #253)."
        )
    id_param = spec.id_param
    extra_deps_named = _name_extra_repo_deps(extra_repo_deps)
    spec_template = spec.form_template

    if on_existing:
        path = f"/{{{id_param}}}/form"
        path_params = (("request", Request), (id_param, UUID))
    else:
        path = "/form"
        path_params = (("request", Request),)

    async def _form(**kwargs: Any) -> Any:
        request: Request = kwargs["request"]
        handler_kwargs: dict[str, Any] = {
            "request": request,
            "repo": kwargs["repo"],
            "requesting_user": kwargs.get("requesting_user"),
            **{name: kwargs[name] for name, _ in extra_deps_named},
        }
        if on_existing:
            handler_kwargs[id_param] = kwargs[id_param]

        context = await _resolve_handler(handler)(**handler_kwargs)
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
            template_name=resolved_template, context=context, request=request
        )

    _set_route_signature(
        _form,
        path_params=path_params,
        deps=_read_route_deps(spec, extra_deps_named),
    )
    router.get(path)(_form)


def mount_create(
    router: Any,
    spec: ResourceSpec,
    handler: Callable[..., Awaitable[Any]],
    *,
    audit_repo_dep: Callable[..., Any],
) -> None:
    """Mount ``POST /<collection>``.

    Parses a form-encoded body via ``spec.create_adapter`` (a Pydantic
    ``TypeAdapter``) and calls the handler with ``payload=``, ``repo=``,
    ``audit_repo=``, ``requesting_user=``. The handler is expected to use
    ``mutate(verb="create")`` so the audit row + commit are owned by the
    context manager.

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
    parent_path_params = _parent_path_param_pairs(spec)

    async def _create(**kwargs: Any) -> Any:
        request: Request = kwargs["request"]
        payload = await parse_and_validate_form(request, create_adapter)
        path_kwargs = _kwargs_for_handler_path(spec, kwargs, with_id=False)
        created = await _resolve_handler(handler)(
            **path_kwargs,
            payload=payload,
            repo=kwargs["repo"],
            audit_repo=kwargs["audit_repo"],
            requesting_user=kwargs["requesting_user"],
        )
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
            # Conservative: redirect to the parent detail page. If a
            # resource needs a different canonical URL it should set
            # create_redirect explicitly (which sets the HX-Redirect; the
            # Location header still points at the parent).
            location = f"/{top.collection}/{top_id}"
        if create_redirect is not None:
            hx = create_redirect(**path_kwargs, **{id_param: created.id})
        else:
            hx = location
        return created_response(id=created.id, location=location, hx_redirect=hx)

    _set_route_signature(
        _create,
        path_params=(("request", Request), *parent_path_params),
        deps=(
            ("repo", spec.repo_dep),
            ("audit_repo", audit_repo_dep),
            ("requesting_user", spec.write_user_dep),
        ),
    )
    router.post(path, status_code=status.HTTP_201_CREATED)(_create)


def mount_update(
    router: Any,
    spec: ResourceSpec,
    handler: Callable[..., Awaitable[Any]],
    *,
    audit_repo_dep: Callable[..., Any],
) -> None:
    """Mount ``PATCH /<collection>/{<id_param>}``.

    Parses a form-encoded body via ``spec.update_adapter`` and calls the
    handler with the resource id (under ``spec.id_param``), ``payload=``,
    ``repo=``, ``audit_repo=``, ``requesting_user=``. Handler uses
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
    parent_path_params = _parent_path_param_pairs(spec)

    async def _update(**kwargs: Any) -> Any:
        request: Request = kwargs["request"]
        payload = await parse_and_validate_form(request, update_adapter)
        path_kwargs = _kwargs_for_handler_path(spec, kwargs, with_id=True)
        updated = await _resolve_handler(handler)(
            **path_kwargs,
            payload=payload,
            repo=kwargs["repo"],
            audit_repo=kwargs["audit_repo"],
            requesting_user=kwargs["requesting_user"],
        )
        body = read_to_dict(updated) if read_to_dict else None
        if update_redirect is not None:
            hx = update_redirect(**path_kwargs)
        else:
            hx = f"/{collection}/{updated.id}"
        return updated_response(body=body, hx_redirect=hx)

    _set_route_signature(
        _update,
        path_params=(("request", Request), *parent_path_params, (id_param, UUID)),
        deps=(
            ("repo", spec.repo_dep),
            ("audit_repo", audit_repo_dep),
            ("requesting_user", spec.write_user_dep),
        ),
    )
    router.patch(path)(_update)


def mount_related_list(
    router: Any,
    parent_spec: ResourceSpec,
    child_spec: ResourceSpec,
    handler: Callable[..., Awaitable[dict]],
    *,
    template: str,
    extra_repo_deps: tuple[Callable[..., Any], ...] = (),
) -> None:
    """Mount ``GET /<parent.collection>/{<parent.id_param>}/<child.collection>``.

    A scoped read of children belonging to a parent — e.g.
    ``GET /users/{user_id}/providers`` lists the providers owned by a user.

    Handler kwargs: ``request``, the parent id under
    ``parent_spec.id_param`` (e.g. ``user_id=...``), ``repo`` (the *child's*
    repo, since the handler returns children), ``requesting_user``, and any
    ``extra_repo_deps`` under their derived kwarg name. Returns a context
    dict; the mount renders ``template``.

    ``template`` is a per-mount kwarg (not on the spec) because related-list
    templates often live in the parent's namespace
    (``users/providers_list.html``, not ``providers/list.html``) — making
    it a per-mount knob keeps both the parent and child specs reusable.

    Auth follows the parent's ``read_user_dep`` (the URL is rooted at the
    parent so its read-auth governs). If the parent is public
    (``read_user_dep=None``), the route is public too.
    """
    if not template:
        raise ValueError(
            "mount_related_list requires `template=` — related-list "
            "templates aren't on the spec because they typically live in "
            "the parent's namespace."
        )
    parent_id_param = parent_spec.id_param
    extra_deps_named = _name_extra_repo_deps(extra_repo_deps)
    path = f"/{{{parent_id_param}}}/{child_spec.collection}"

    async def _related_list(**kwargs: Any) -> Any:
        request: Request = kwargs["request"]
        parent_id: UUID = kwargs[parent_id_param]
        context = await _resolve_handler(handler)(
            request=request,
            **{parent_id_param: parent_id},
            repo=kwargs["repo"],
            requesting_user=kwargs.get("requesting_user"),
            **{name: kwargs[name] for name, _ in extra_deps_named},
        )
        return APIResponse.html_response(
            template_name=template, context=context, request=request
        )

    deps: list[tuple[str, Callable[..., Any]]] = [("repo", child_spec.repo_dep)]
    if parent_spec.read_user_dep is not None:
        deps.append(("requesting_user", parent_spec.read_user_dep))
    deps.extend(extra_deps_named)

    _set_route_signature(
        _related_list,
        path_params=(("request", Request), (parent_id_param, UUID)),
        deps=tuple(deps),
    )
    router.get(path)(_related_list)


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


def _kwargs_for_handler_path(
    spec: ResourceSpec, kwargs: dict[str, Any], *, with_id: bool
) -> dict[str, Any]:
    """Pluck the parent ids (and the spec's own id if ``with_id``) out of
    the route's kwargs into a fresh dict suitable for splatting into a
    handler call as ``**path_kwargs``."""
    out: dict[str, Any] = {}
    for name, _ in _parent_path_param_pairs(spec):
        out[name] = kwargs[name]
    if with_id:
        out[spec.id_param] = kwargs[spec.id_param]
    return out


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


def _name_extra_repo_deps(
    deps: tuple[Callable[..., Any], ...],
) -> tuple[tuple[str, Callable[..., Any]], ...]:
    """Derive the kwarg name each extra repo dep is passed under.

    Convention: ``get_provider_repository`` → ``provider_repo``,
    ``get_audit_repository`` → ``audit_repo``. Strips the ``get_`` prefix
    and the ``ository`` suffix on ``_repository``. If a dep has a name
    that doesn't match the convention, raise — silent name-mismatches
    would be a bug at the kwarg-injection site.
    """
    out: list[tuple[str, Callable[..., Any]]] = []
    for dep in deps:
        name = getattr(dep, "__name__", None)
        if not name or not name.startswith("get_"):
            raise ValueError(
                f"extra_repo_deps callable {dep!r} must be named "
                "'get_<entity>_repository' so the kwarg can be derived."
            )
        bare = name[len("get_") :]
        if bare.endswith("_repository"):
            kwarg = bare[: -len("_repository")] + "_repo"
        else:
            kwarg = bare
        out.append((kwarg, dep))
    return tuple(out)


def _read_route_deps(
    spec: ResourceSpec,
    extra_deps_named: tuple[tuple[str, Callable[..., Any]], ...],
) -> tuple[tuple[str, Callable[..., Any]], ...]:
    """Build the (kwarg, callable) pairs for the dep-injected params on a
    read route. Includes the primary repo, optional read user dep, and
    each extra repo. ``read_user_dep=None`` means public — the route is
    mounted without a user dep, and the handler receives
    ``requesting_user=None``."""
    deps: list[tuple[str, Callable[..., Any]]] = [("repo", spec.repo_dep)]
    if spec.read_user_dep is not None:
        deps.append(("requesting_user", spec.read_user_dep))
    deps.extend(extra_deps_named)
    return tuple(deps)


def _set_route_signature(
    fn: Callable[..., Any],
    *,
    path_params: tuple[tuple[str, type], ...],
    deps: tuple[tuple[str, Callable[..., Any]], ...],
) -> None:
    """Advertise an explicit signature on a `**kwargs`-based route handler.

    FastAPI introspects `inspect.signature(fn)` to figure out path params
    and dependencies. The mount helpers define the actual handler with
    `**kwargs` (so the parameter names can be data-driven from the
    `ResourceSpec`) and call this to publish the signature FastAPI sees.

    `path_params` are positional-or-keyword params with a type annotation
    and no default — FastAPI binds them from the URL.
    `deps` are positional-or-keyword params whose default is `Depends(...)`
    — FastAPI resolves them via the injection system.
    """
    from inspect import Parameter, Signature

    params: list[Parameter] = []
    for name, ann in path_params:
        params.append(
            Parameter(
                name=name,
                kind=Parameter.POSITIONAL_OR_KEYWORD,
                annotation=ann,
            )
        )
    for name, dep in deps:
        params.append(
            Parameter(
                name=name,
                kind=Parameter.POSITIONAL_OR_KEYWORD,
                default=Depends(dep),
                annotation=Any,
            )
        )
    fn.__signature__ = Signature(parameters=params)  # type: ignore[attr-defined]
