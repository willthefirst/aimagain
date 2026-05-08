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

from fastapi import Depends, status
from pydantic import TypeAdapter

from src.api.common.responses import deleted_response
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
      extra_repo_deps: ``Depends`` providers for any *additional*
        repositories the handler needs beyond the primary ``repo_dep``.
        Mount functions inject these by their dep callable's name
        (minus the ``get_`` prefix). Used by handlers like
        ``handle_get_user_detail`` that take both a user repo and a
        provider repo. Empty for the common single-repo case.
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

    extra_repo_deps: tuple[Callable[..., Any], ...] = ()

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

    Until slice 8 (#253) sub-resource support lands, this asserts
    ``spec.parent is None``. The path is just ``/{<id_param>}`` —
    callers register the router with the resource's collection prefix
    (e.g. ``APIRouter(prefix="/users")``).
    """
    if spec.parent is not None:
        raise NotImplementedError(
            "mount_delete with spec.parent is not supported yet "
            "(slice 8 / issue #253). Use register_subresource_routes for now."
        )
    if spec.write_user_dep is None:
        raise ValueError(
            f"mount_delete requires {spec.collection!r} to set "
            "write_user_dep — silent public deletes would be a bug."
        )

    path = f"/{{{spec.id_param}}}"
    id_param = spec.id_param
    delete_redirect = spec.delete_redirect
    default_redirect = f"/{spec.collection}"

    async def _delete(**kwargs: Any) -> Any:
        # FastAPI binds the path param under `id_param`, the deps under
        # the names declared in `__signature__` below.
        resource_id = kwargs[id_param]
        await handler(
            **{id_param: resource_id},
            repo=kwargs["repo"],
            audit_repo=kwargs["audit_repo"],
            requesting_user=kwargs["requesting_user"],
        )
        if delete_redirect is not None:
            hx_redirect = delete_redirect(**{id_param: resource_id})
        else:
            hx_redirect = default_redirect
        return deleted_response(hx_redirect=hx_redirect)

    _set_route_signature(
        _delete,
        path_params=((id_param, UUID),),
        deps=(
            ("repo", spec.repo_dep),
            ("audit_repo", audit_repo_dep),
            ("requesting_user", spec.write_user_dep),
        ),
    )

    router.delete(path, status_code=status.HTTP_204_NO_CONTENT)(_delete)


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
