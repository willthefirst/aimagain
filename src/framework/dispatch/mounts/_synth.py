"""Route-function signature synthesis.

`synthesize_route_fn` introspects each handler's typed signature and
pairs every parameter with the right source (path / Depends / Query /
body parser). The handler's signature becomes the single source of
truth: forgetting to wire a dep is a registration-time `MountError`,
not a first-request crash.

Each mount supplies the response shape via `response_builder`. The
synthesis helper handles the boring middle: introspection, signature
construction, kwarg routing.
"""

import inspect
import types
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Union, get_args, get_origin
from uuid import UUID

from fastapi import Depends, Query, Request
from pydantic import BaseModel, TypeAdapter

from src.framework.dispatch.mounts._spec import _UNSET, QueryParam, ResourceSpec
from src.framework.persistence.dependencies import UnknownRepoTypeError, resolver_for


class MountError(TypeError):
    """Raised at mount-registration time when the handler signature is
    incompatible with what the mount can supply. The error names the
    handler, the offending parameter, and (where applicable) the type
    that lacks a registry entry. App startup fails immediately rather
    than the first request 500-ing."""


def is_optional(annotation: Any) -> tuple[bool, Any]:
    """If `annotation` is `T | None` / `Optional[T]`, return `(True, T)`;
    otherwise `(False, annotation)`. Handles both the 3.10+ pipe syntax
    (`types.UnionType`) and `typing.Union[..., None]`."""
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1 and type(None) in get_args(annotation):
            return True, args[0]
    return False, annotation


def is_pydantic_model(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


@dataclass(frozen=True)
class SynthOptions:
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


def synthesize_route_fn(
    *,
    handler: Callable[..., Any],
    spec: ResourceSpec,
    options: SynthOptions,
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
    calling the handler (via `resolve_handler`) and returning the
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
        is_opt, base_ann = is_optional(annotation)

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
