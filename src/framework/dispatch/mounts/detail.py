"""`mount_detail` — `GET /<collection>/{<id_param>}`.

Also owns `handle_detail` and `make_detail_handler` — the generic
detail handler and its factory, originally in `handlers.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable
from uuid import UUID

from fastapi import Request

from src.framework.access.actor.actor import Actor
from src.framework.access.authz.authz import is_admin
from src.framework.dispatch.mounts._common import (
    assert_kind_lock,
    call_handler_with,
)
from src.framework.dispatch.mounts._spec import ResourceSpec
from src.framework.dispatch.mounts._synth import SynthOptions, synthesize_route_fn
from src.framework.http.exceptions import NotFoundError
from src.framework.http.responses import APIResponse
from src.framework.persistence.base_repository import BaseRepository
from src.framework.rendering.projections import project_view

if TYPE_CHECKING:
    from src.framework.dispatch.entity_spec import EntitySpec


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
    user repo and a clinician repo) just requires the handler to declare
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


async def handle_detail(
    spec: EntitySpec,
    *,
    request: Request,
    target_id: UUID,
    repo: BaseRepository,
    requesting_user: Actor | None,
    extras: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    extra_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generic detail handler driven by `spec`; merges spec-driven
    context with the entity's `extras` callable (last-write-wins)."""
    target = await repo.get_by_model_id(spec.model, target_id)
    if target is None:
        raise NotFoundError(detail=f"{spec.name.capitalize()} not found")
    assert_kind_lock(spec, target)

    from src.framework.rendering.route_urls import url_for_spec

    context: dict[str, Any] = {
        "request": request,
        spec.name: target,
        # Shared partials (e.g. `_shared/posts/_owner_actions.html`)
        # read `entity_name` to build kind-aware URLs via
        # `entity_url(entity_name, ...)`. Set on every detail render so
        # included partials don't have to walk back through caller
        # context.
        "entity_name": spec.name,
        "current_user": requesting_user,
        # Detail templates' breadcrumb back-link to the collection
        # used to set `resource_url` via a `{% set %}` line; inject
        # here so child templates skip the boilerplate.
        "resource_url": url_for_spec(spec),
    }
    if spec.can_write is not None:
        context["can_edit"] = spec.can_write(target, requesting_user)

    # Viewer-derived flags. `subject_attr` is the attribute on `target`
    # whose value equals `requesting_user.id` when the viewer IS the
    # subject — for `owner_attr=None` (users — the row IS the user), the
    # rule reduces to `target.id == viewer.id`; for owned resources
    # (clinician, post), it uses the owner FK. The uniform rule lets every
    # entity inherit `is_self` / `can_admin_actions` without per-entity glue.
    subject_attr = spec.owner_attr or "id"
    is_self = (
        requesting_user is not None
        and getattr(target, subject_attr) == requesting_user.id
    )
    context["is_self"] = is_self
    context["can_admin_actions"] = is_admin(requesting_user) and not is_self

    if spec.private_field_predicate is not None:
        context["can_view_private"] = bool(
            spec.private_field_predicate(requesting_user, target)
        )

    if spec.public_fields:
        context[f"target_{spec.name}"] = project_view(
            target,
            public_fields=spec.public_fields,
            actor=requesting_user,
            private_fields=spec.private_fields,
            private_field_predicate=spec.private_field_predicate,
        )

    # Spec-declared constants — merged before extras so an extras
    # callable can still override (last-write-wins, matching the
    # framework's existing precedence rule).
    if spec.static_context:
        context.update(spec.static_context)

    if extras is not None:
        extras_kwargs = {
            "target": target,
            "request": request,
            "requesting_user": requesting_user,
        }
        if extra_kwargs:
            extras_kwargs.update(extra_kwargs)
        context.update(await extras(**extras_kwargs))

    return context


def make_detail_handler(
    spec: EntitySpec,
    *,
    extras: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    extra_repos: tuple[tuple[str, type], ...] = (),
):
    from src.framework.dispatch.mounts._factory import (
        _DETAIL_SHAPE,
        _make_factory_handler,
    )

    return _make_factory_handler(
        spec, _DETAIL_SHAPE, handle_detail, extras=extras, extra_repos=extra_repos
    )
