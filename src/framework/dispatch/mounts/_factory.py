"""Shared factory infrastructure for the per-verb ``make_*_handler`` functions.

Each verb module (``create.py``, ``delete.py``, etc.) imports
``_FactoryShape``, the pre-built shape constants, ``_param``, and
``_make_factory_handler`` from here. Keeping this in the ``mounts``
package eliminates the old inward dependency on
``src.framework.dispatch.handlers``.
"""

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel

from src.framework.actor import Actor
from src.framework.audit.repository import AuditRepository
from src.framework.dispatch.filters import Filter
from src.framework.dispatch.pagination import (  # noqa: F401
    DEFAULT_PAGE_SIZE,
    Pager,
    base_query,
    offset_for,
    paginate,
    parse_page,
)
from src.framework.persistence.base_repository import BaseRepository


@dataclass(frozen=True, slots=True)
class _FactoryShape:
    """Declarative shape of one verb's factory-built handler."""

    name_template: str
    include_request: bool = False
    include_target_id: bool = False
    include_parent_id: bool = False
    include_payload: bool = False
    include_audit_repo: bool = False
    include_filters: bool = False
    accepts_extras: bool = False
    user_optional: bool = False
    # The new-form path doesn't load a target, so the synthesized
    # handler omits `repo`; mount_form passes only declared kwargs.
    omit_repo: bool = False
    # Polymorphic entities' create-form takes `?kind=` as a query param.
    include_kind_for_polymorphic: bool = False
    # Verbs that route through `payload_authz` (create / update). When
    # True, `_make_factory_handler` accepts optional `payload_authz`
    # and `payload_authz_repos` kwargs, synthesizes signature params
    # for each declared typed repo, and forwards the resolved callable
    # plus the collected typed-repo dict to the underlying handler.
    payload_authz_call: bool = False
    # Verbs that route through `after_create` (create only). Mirror of
    # the `payload_authz_call` plumbing — `_make_factory_handler`
    # accepts optional `after_create` + `after_create_repos`, synthesizes
    # signature params for each declared typed repo, and forwards both
    # to the underlying handler.
    after_create_call: bool = False


_DELETE_SHAPE = _FactoryShape(
    name_template="_handle_delete_{name}",
    include_target_id=True,
    include_parent_id=True,
    include_audit_repo=True,
)
_CREATE_SHAPE = _FactoryShape(
    name_template="_handle_create_{name}",
    include_payload=True,
    include_parent_id=True,
    include_audit_repo=True,
    payload_authz_call=True,
    after_create_call=True,
)
_UPDATE_SHAPE = _FactoryShape(
    name_template="_handle_update_{name}",
    include_target_id=True,
    include_payload=True,
    include_parent_id=True,
    include_audit_repo=True,
    payload_authz_call=True,
)
_EDIT_FORM_SHAPE = _FactoryShape(
    name_template="_handle_get_{name}_edit_form",
    include_request=True,
    include_target_id=True,
    accepts_extras=True,
)
_NEW_FORM_SHAPE = _FactoryShape(
    name_template="_handle_get_{name}_new_form",
    include_request=True,
    include_kind_for_polymorphic=True,
    omit_repo=True,
    accepts_extras=True,
)
_DETAIL_SHAPE = _FactoryShape(
    name_template="_handle_get_{name}_detail",
    include_request=True,
    include_target_id=True,
    accepts_extras=True,
    user_optional=True,
)
_LIST_SHAPE = _FactoryShape(
    name_template="_handle_list_{name}",
    include_request=True,
    include_filters=True,
    accepts_extras=True,
    user_optional=True,
)


def _param(name: str, annotation: Any) -> inspect.Parameter:
    return inspect.Parameter(
        name, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=annotation
    )


def _make_factory_handler(
    spec: Any,  # EntitySpec — typed as Any to avoid a cross-package import cycle
    shape: _FactoryShape,
    handler_fn: Callable[..., Awaitable[Any]],
    *,
    extras: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    extra_repos: tuple[tuple[str, type], ...] = (),
    payload_authz: Callable[..., Awaitable[None]] | None = None,
    payload_authz_repos: tuple[tuple[str, type], ...] = (),
    after_create: Callable[..., Awaitable[None]] | None = None,
    after_create_repos: tuple[tuple[str, type], ...] = (),
):
    """Build the wrapper the mount layer introspects and calls.

    For shapes with ``payload_authz_call=True`` (create / update), each
    entry in ``payload_authz_repos`` becomes an extra signature
    parameter (``name: RepoType``); at call time the collected kwargs
    are forwarded to the underlying handler as ``payload_authz_kwargs``
    alongside the ``payload_authz`` callable itself.
    """
    id_param = spec.id_param
    parent_id_param = spec.parent.id_param if spec.parent is not None else None
    # Collision detection: ``payload_authz_repos`` names mustn't shadow
    # the fixed signature params the factory generates (``payload``,
    # ``repo``, ``audit_repo``, ``requesting_user``, the entity's
    # ``id_param``, and the parent's ``id_param`` if any). Synthesizing
    # a duplicate `inspect.Parameter` would silently overwrite the
    # earlier slot; surface the misconfig loudly.
    payload_authz_repo_names = (
        tuple(name for name, _ in payload_authz_repos)
        if shape.payload_authz_call
        else ()
    )
    after_create_repo_names = (
        tuple(name for name, _ in after_create_repos) if shape.after_create_call else ()
    )
    if shape.payload_authz_call or shape.after_create_call:
        reserved = {
            "payload",
            "repo",
            "audit_repo",
            "requesting_user",
            id_param,
        }
        if parent_id_param is not None:
            reserved.add(parent_id_param)
        clashes = [
            n
            for n in (*payload_authz_repo_names, *after_create_repo_names)
            if n in reserved
        ]
        if clashes:
            raise ValueError(
                f"_make_factory_handler({spec.name!r}): payload_authz_repos / "
                f"after_create_repos name(s) {clashes!r} collide with the "
                "factory-generated signature params — pick distinct names."
            )
        # Names must also not collide with each other (a single
        # `inspect.Parameter` per name).
        seen: set[str] = set()
        for n in (*payload_authz_repo_names, *after_create_repo_names):
            if n in seen:
                raise ValueError(
                    f"_make_factory_handler({spec.name!r}): repo name "
                    f"{n!r} declared in both payload_authz_repos and "
                    "after_create_repos — synthesize one slot, share it via "
                    "a single declaration."
                )
            seen.add(n)
    # `spec.filters` accepts raw `QueryParam` (legacy) or `Filter`
    # subclasses (URL + UI metadata). Both expose the URL shape via the
    # same `name` / `annotation` pair — `Filter` via `to_query_param()`.
    # Normalize once so the rest of the factory only deals in
    # `QueryParam`.
    filter_query_params: tuple[Any, ...] = (
        tuple(f.to_query_param() if isinstance(f, Filter) else f for f in spec.filters)
        if shape.include_filters
        else ()
    )
    filter_names = tuple(qp.name for qp in filter_query_params)
    extra_repo_names = tuple(name for name, _ in extra_repos)

    sig_params: list[inspect.Parameter] = []
    if shape.include_request:
        sig_params.append(_param("request", Request))
    if shape.include_parent_id and parent_id_param is not None:
        sig_params.append(_param(parent_id_param, UUID))
    if shape.include_target_id:
        sig_params.append(_param(id_param, UUID))
    if shape.include_filters:
        for qp in filter_query_params:
            sig_params.append(_param(qp.name, qp.annotation))
    if shape.include_payload:
        sig_params.append(_param("payload", BaseModel))
    # The polymorphic-supertype create-form takes `?kind=` as a query
    # param so the picker can dispatch to the right kind's template.
    # Kind-locked faces (`discriminator_value` set) bypass the picker
    # entirely — the handler uses `spec.discriminator_value` directly,
    # so no `kind` route param is registered.
    include_kind_param = (
        shape.include_kind_for_polymorphic
        and spec.discriminator is not None
        and spec.discriminator_value is None
    )
    if include_kind_param:
        sig_params.append(_param("kind", str))
    if not shape.omit_repo:
        sig_params.append(_param("repo", BaseRepository))
    if shape.include_audit_repo:
        sig_params.append(_param("audit_repo", AuditRepository))
    user_ann = Actor | None if shape.user_optional else Actor
    sig_params.append(_param("requesting_user", user_ann))
    for name, repo_type in extra_repos:
        sig_params.append(_param(name, repo_type))
    if shape.payload_authz_call:
        for name, repo_type in payload_authz_repos:
            sig_params.append(_param(name, repo_type))
    if shape.after_create_call:
        # Skip names already added via `payload_authz_repos` — a spec
        # can reuse the same repo for both hooks; one slot is enough.
        existing = set(payload_authz_repo_names) if shape.payload_authz_call else set()
        for name, repo_type in after_create_repos:
            if name in existing:
                continue
            sig_params.append(_param(name, repo_type))

    async def _handler(**kwargs: Any) -> Any:
        call_kwargs: dict[str, Any] = {
            "requesting_user": kwargs["requesting_user"],
        }
        if not shape.omit_repo:
            call_kwargs["repo"] = kwargs["repo"]
        if include_kind_param:
            call_kwargs["kind"] = kwargs["kind"]
        if shape.include_request:
            call_kwargs["request"] = kwargs["request"]
        if shape.include_target_id:
            call_kwargs["target_id"] = kwargs[id_param]
        if shape.include_parent_id:
            call_kwargs["parent_id"] = (
                kwargs[parent_id_param] if parent_id_param else None
            )
        if shape.include_payload:
            call_kwargs["payload"] = kwargs["payload"]
        if shape.include_audit_repo:
            call_kwargs["audit_repo"] = kwargs["audit_repo"]
        if shape.include_filters:
            call_kwargs["filter_values"] = {n: kwargs[n] for n in filter_names}
        if shape.accepts_extras:
            collected = {n: kwargs[n] for n in extra_repo_names}
            call_kwargs["extras"] = extras
            call_kwargs["extra_kwargs"] = collected if collected else None
        if shape.payload_authz_call and payload_authz is not None:
            call_kwargs["payload_authz"] = payload_authz
            call_kwargs["payload_authz_kwargs"] = {
                n: kwargs[n] for n in payload_authz_repo_names
            }
        if shape.after_create_call and after_create is not None:
            call_kwargs["after_create"] = after_create
            call_kwargs["after_create_kwargs"] = {
                n: kwargs[n] for n in after_create_repo_names
            }
        return await handler_fn(spec, **call_kwargs)

    _handler.__signature__ = inspect.Signature(parameters=sig_params)  # type: ignore[attr-defined]
    _handler.__name__ = shape.name_template.format(name=spec.name)
    _handler.__qualname__ = _handler.__name__
    return _handler
