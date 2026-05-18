"""Generic dispatch handlers driven by EntitySpec."""

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel

from src.framework.actor import Actor
from src.framework.audit.core import mutate
from src.framework.audit.repository import AuditRepository
from src.framework.authz import is_admin
from src.framework.dispatch.entity_spec import EntitySpec
from src.framework.dispatch.filters import Filter
from src.framework.dispatch.pagination import (
    DEFAULT_PAGE_SIZE,
    base_query,
    offset_for,
    paginate,
    parse_page,
)
from src.framework.http.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.framework.persistence.base_repository import BaseRepository
from src.framework.rendering.projections import project_view


async def handle_delete(
    spec: EntitySpec,
    *,
    target_id: UUID,
    repo: BaseRepository,
    audit_repo: AuditRepository,
    requesting_user: Actor,
    parent_id: UUID | None = None,
) -> None:
    """Generic delete handler driven by `spec`."""
    if spec.audit is None:
        raise ValueError(
            f"handle_delete: spec {spec.name!r} has no audit binding; "
            "delete operations must be audited."
        )

    target = await repo.get_by_model_id(spec.model, target_id)
    if target is None:
        raise NotFoundError(detail=f"{spec.name.capitalize()} not found")

    # Self-target guard for user-shaped entities — the comparison only
    # matches when `target.id` IS the requesting user's id (i.e. the row
    # is a user). For owned resources, target.id is a row UUID, so the
    # comparison is harmless. See `EntitySpec.delete_forbid_self`.
    if spec.delete_forbid_self and target.id == requesting_user.id:
        raise ForbiddenError(
            detail=f"Cannot delete your own {spec.name} via this endpoint"
        )

    if spec.parent is not None:
        if parent_id is None:
            raise ValueError(
                f"handle_delete: spec {spec.name!r} has parent "
                f"{spec.parent.name!r} but no parent_id was supplied."
            )
        # Subentity convention: the child's FK column is named
        # `<parent.name>_id`. Verify the URL's parent id matches the
        # child's persisted FK — otherwise `/parents/A/children/B`
        # would silently delete a child owned by parent B.
        parent_fk_attr = f"{spec.parent.name}_id"
        if getattr(target, parent_fk_attr) != parent_id:
            raise NotFoundError(detail=f"{spec.name.capitalize()} not found")
        parent = await repo.get_by_model_id(spec.parent.model, parent_id)
        if parent is None:
            raise NotFoundError(detail=f"{spec.parent.name.capitalize()} not found")
        if spec.write_authz is not None:
            spec.write_authz(parent, requesting_user, action=f"delete this {spec.name}")
    else:
        if spec.write_authz is not None:
            spec.write_authz(target, requesting_user, action=f"delete this {spec.name}")

    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=target,
        resource=spec.audit,
        verb="delete",
    ):
        await repo.delete(target)


async def handle_create(
    spec: EntitySpec,
    *,
    payload: BaseModel,
    repo: BaseRepository,
    audit_repo: AuditRepository,
    requesting_user: Actor,
    parent_id: UUID | None = None,
    payload_authz: Callable[..., Awaitable[None]] | None = None,
    payload_authz_kwargs: dict[str, Any] | None = None,
) -> Any:
    """Generic create handler driven by `spec`.

    `payload_authz` (if supplied) is invoked AFTER the parent row has
    been loaded and `write_authz` has run on it (if applicable), and
    BEFORE the payload is used to build the model. The callable is
    expected to raise `ForbiddenError` / `NotFoundError` on rejection;
    `payload_authz_kwargs` supplies any spec-declared typed repo kwargs.
    See `EntitySpec.payload_authz_path` for the contract."""
    if spec.audit is None:
        raise ValueError(
            f"handle_create: spec {spec.name!r} has no audit binding; "
            "create operations must be audited."
        )

    if spec.parent is not None:
        if parent_id is None:
            raise ValueError(
                f"handle_create: spec {spec.name!r} has parent "
                f"{spec.parent.name!r} but no parent_id was supplied."
            )
        parent = await repo.get_by_model_id(spec.parent.model, parent_id)
        if parent is None:
            raise NotFoundError(detail=f"{spec.parent.name.capitalize()} not found")
        if spec.write_authz is not None:
            spec.write_authz(parent, requesting_user, action=f"create this {spec.name}")
        if payload_authz is not None:
            await payload_authz(
                payload=payload,
                requesting_user=requesting_user,
                **(payload_authz_kwargs or {}),
            )
        child = spec.model(**payload.model_dump())
        created = await repo.add_child(parent, spec.url_collection, child)

    elif spec.discriminator is not None:
        if payload_authz is not None:
            await payload_authz(
                payload=payload,
                requesting_user=requesting_user,
                **(payload_authz_kwargs or {}),
            )
        kind = payload.kind
        kind_spec = spec.discriminator[kind]
        # Read detail fields off the serialized dump, not via
        # ``getattr``, so wire-flat / schema-nested fields (e.g. the
        # post-#451 ``location: Location`` value object on
        # :class:`ReferralCreate`, which serializes back to flat
        # ``location_city`` / ``location_state`` / ``location_zip`` keys
        # via ``flatten_location_on_dump``) line up with the ORM
        # model's flat columns enumerated in ``detail_fields``.
        dump = payload.model_dump()
        detail = kind_spec.detail_model(
            **{f: dump[f] for f in kind_spec.detail_fields if f in dump}
        )
        parent_obj = spec.model(**{spec.discriminator.column: kind})
        if spec.owner_attr is not None:
            setattr(parent_obj, spec.owner_attr, requesting_user.id)
        created = await repo.create_polymorphic(
            parent_obj, detail, detail_relationship=kind_spec.detail_relationship
        )

    else:
        if payload_authz is not None:
            await payload_authz(
                payload=payload,
                requesting_user=requesting_user,
                **(payload_authz_kwargs or {}),
            )
        # Inline-child collections (e.g. provider's licensures /
        # educations / certifications) come in on the payload alongside
        # the parent's own fields. Exclude them from the parent
        # constructor, persist the parent, then append each child via
        # `repo.add_child` so the in-memory state stays coherent for
        # the audit after-snapshot. Empty `spec.children` is the common
        # case (most entities have no inline children) and the loop is
        # a no-op.
        inline_collections = tuple(c.url_collection for c in spec.children)
        parent_fields = payload.model_dump(exclude=set(inline_collections))
        instance = spec.model(**parent_fields)
        if spec.owner_attr is not None:
            setattr(instance, spec.owner_attr, requesting_user.id)
        created = await repo.create(instance)
        for child_spec in spec.children:
            for item in getattr(payload, child_spec.url_collection, []) or []:
                await repo.add_child(
                    created,
                    child_spec.url_collection,
                    child_spec.model(**item.model_dump()),
                )

    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=created,
        resource=spec.audit,
        verb="create",
    ):
        pass
    return created


async def handle_update(
    spec: EntitySpec,
    *,
    target_id: UUID,
    payload: BaseModel,
    repo: BaseRepository,
    audit_repo: AuditRepository,
    requesting_user: Actor,
    parent_id: UUID | None = None,
    payload_authz: Callable[..., Awaitable[None]] | None = None,
    payload_authz_kwargs: dict[str, Any] | None = None,
) -> Any:
    """Generic update handler driven by `spec`.

    `payload_authz` (if supplied) is invoked AFTER the target 404 check
    and AFTER `write_authz` has run on parent-or-target, and BEFORE the
    payload is consumed (discriminator dispatch / patch). When the
    target 404s, the hook is never called — the 404 fires first. See
    `EntitySpec.payload_authz_path` for the contract."""
    if spec.audit is None:
        raise ValueError(
            f"handle_update: spec {spec.name!r} has no audit binding; "
            "update operations must be audited."
        )

    target = await repo.get_by_model_id(spec.model, target_id)
    if target is None:
        raise NotFoundError(detail=f"{spec.name.capitalize()} not found")

    if spec.parent is not None:
        if parent_id is None:
            raise ValueError(
                f"handle_update: spec {spec.name!r} has parent "
                f"{spec.parent.name!r} but no parent_id was supplied."
            )
        parent_fk_attr = f"{spec.parent.name}_id"
        if getattr(target, parent_fk_attr) != parent_id:
            raise NotFoundError(detail=f"{spec.name.capitalize()} not found")
        parent = await repo.get_by_model_id(spec.parent.model, parent_id)
        if parent is None:
            raise NotFoundError(detail=f"{spec.parent.name.capitalize()} not found")
        if spec.write_authz is not None:
            spec.write_authz(parent, requesting_user, action=f"update this {spec.name}")
    else:
        if spec.write_authz is not None:
            spec.write_authz(target, requesting_user, action=f"update this {spec.name}")

    if payload_authz is not None:
        await payload_authz(
            payload=payload,
            requesting_user=requesting_user,
            **(payload_authz_kwargs or {}),
        )

    if spec.discriminator is not None:
        payload_kind = payload.kind
        target_kind = getattr(target, spec.discriminator.column)
        if payload_kind != target_kind:
            raise BadRequestError(
                detail=(
                    f"payload kind {payload_kind!r} does not match {spec.name} "
                    f"kind {target_kind!r}; kind cannot be changed via PATCH"
                )
            )
        kind_spec = spec.discriminator[target_kind]
        detail = getattr(target, kind_spec.detail_relationship)
        # ``model_dump(exclude_unset=True)`` picks up only the fields
        # the client touched and — via the schema's flatten-on-dump
        # ``model_serializer`` (post-#451) — re-projects any nested
        # value-object fields (e.g. ``location: LocationPartial``)
        # back to the flat column names ``detail_fields`` enumerates.
        # Restrict to ``detail_fields`` so the discriminator (``kind``)
        # and any other top-level keys never reach ``repo.patch``.
        dump = payload.model_dump(exclude_unset=True)
        update_fields = {f: dump[f] for f in kind_spec.detail_fields if f in dump}
        async with mutate(
            repo,
            audit_repo,
            actor=requesting_user,
            target=target,
            resource=spec.audit,
            verb="update",
        ):
            await repo.patch(detail, **update_fields)
        return target

    update_fields = payload.model_dump(exclude_unset=True)
    async with mutate(
        repo,
        audit_repo,
        actor=requesting_user,
        target=target,
        resource=spec.audit,
        verb="update",
    ):
        await repo.patch(target, **update_fields)
    return target


# Each `make_<verb>_handler` factory fabricates a callable with a typed
# signature so the route mount layer's introspection can bind URL path
# params, body adapters, query filters, and `Depends` to the right
# handler kwargs. `_FactoryShape` encodes the per-verb differences and
# `_make_factory_handler` builds the signature + wrapper once.


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
    spec: EntitySpec,
    shape: _FactoryShape,
    handler_fn: Callable[..., Awaitable[Any]],
    *,
    extras: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    extra_repos: tuple[tuple[str, type], ...] = (),
    payload_authz: Callable[..., Awaitable[None]] | None = None,
    payload_authz_repos: tuple[tuple[str, type], ...] = (),
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
    if shape.payload_authz_call and payload_authz_repo_names:
        reserved = {
            "payload",
            "repo",
            "audit_repo",
            "requesting_user",
            id_param,
        }
        if parent_id_param is not None:
            reserved.add(parent_id_param)
        clashes = [n for n in payload_authz_repo_names if n in reserved]
        if clashes:
            raise ValueError(
                f"_make_factory_handler({spec.name!r}): payload_authz_repos "
                f"name(s) {clashes!r} collide with the factory-generated "
                "signature params — pick distinct names."
            )
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
    if shape.include_kind_for_polymorphic and spec.discriminator is not None:
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

    async def _handler(**kwargs: Any) -> Any:
        call_kwargs: dict[str, Any] = {
            "requesting_user": kwargs["requesting_user"],
        }
        if not shape.omit_repo:
            call_kwargs["repo"] = kwargs["repo"]
        if shape.include_kind_for_polymorphic and spec.discriminator is not None:
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
        return await handler_fn(spec, **call_kwargs)

    _handler.__signature__ = inspect.Signature(parameters=sig_params)  # type: ignore[attr-defined]
    _handler.__name__ = shape.name_template.format(name=spec.name)
    _handler.__qualname__ = _handler.__name__
    return _handler


def make_delete_handler(spec: EntitySpec):
    return _make_factory_handler(spec, _DELETE_SHAPE, handle_delete)


def make_create_handler(
    spec: EntitySpec,
    *,
    payload_authz: Callable[..., Awaitable[None]] | None = None,
    payload_authz_repos: tuple[tuple[str, type], ...] = (),
):
    return _make_factory_handler(
        spec,
        _CREATE_SHAPE,
        handle_create,
        payload_authz=payload_authz,
        payload_authz_repos=payload_authz_repos,
    )


def make_update_handler(
    spec: EntitySpec,
    *,
    payload_authz: Callable[..., Awaitable[None]] | None = None,
    payload_authz_repos: tuple[tuple[str, type], ...] = (),
):
    return _make_factory_handler(
        spec,
        _UPDATE_SHAPE,
        handle_update,
        payload_authz=payload_authz,
        payload_authz_repos=payload_authz_repos,
    )


async def handle_get_edit_form(
    spec: EntitySpec,
    *,
    request: Request,
    target_id: UUID,
    repo: BaseRepository,
    requesting_user: Actor,
    extras: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    extra_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generic edit-form handler driven by `spec`.

    When `extras` is set (threaded in by `make_edit_form_handler` from
    the spec's `form_extras_path`), the callable is invoked with
    ``target=<loaded row>``, ``request``, ``requesting_user``, and any
    typed-repo kwargs declared via `form_extras_repos`. The returned
    dict merges into the form context (last-write-wins, mirroring
    `handle_detail` / `handle_list`)."""
    target = await repo.get_by_model_id(spec.model, target_id)
    if target is None:
        raise NotFoundError(detail=f"{spec.name.capitalize()} not found")
    if spec.write_authz is not None:
        spec.write_authz(target, requesting_user, action=f"edit this {spec.name}")

    context: dict[str, Any] = {
        "request": request,
        spec.name: target,
        "current_user": requesting_user,
    }
    # Spec-declared constants (enum labels, schema classes the form
    # references, etc.) — same merge precedence as detail/list.
    if spec.static_context:
        context.update(spec.static_context)
    if spec.discriminator is not None:
        kind = getattr(target, spec.discriminator.column)
        context["template_name"] = spec.discriminator[kind].edit_template

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


def make_edit_form_handler(
    spec: EntitySpec,
    *,
    extras: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    extra_repos: tuple[tuple[str, type], ...] = (),
):
    return _make_factory_handler(
        spec,
        _EDIT_FORM_SHAPE,
        handle_get_edit_form,
        extras=extras,
        extra_repos=extra_repos,
    )


async def handle_get_new_form(
    spec: EntitySpec,
    *,
    request: Request,
    requesting_user: Actor,
    kind: str | None = None,
    extras: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    extra_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generic create-form handler driven by `spec`.

    For polymorphic entities (those with a `discriminator`):
      * `kind=None` (no `?kind=` on the URL) → don't set `template_name`,
        so the route falls back to `spec.form_template` and renders the
        picker template (conventionally `<collection>/form_new.html`).
        The picker lists the available kinds; users pick one and round-
        trip back to this handler with `?kind=…`.
      * `kind=<value>` → set `template_name` to the kind's
        `create_template` so the route renders the kind-specific form.
    """
    context: dict[str, Any] = {
        "request": request,
        "current_user": requesting_user,
    }
    if spec.static_context:
        context.update(spec.static_context)
    if spec.discriminator is not None:
        if kind is not None:
            context["template_name"] = spec.discriminator[kind].create_template
        # When `kind is None`, leave `template_name` unset so the route
        # falls through to `spec.form_template` (the picker).
    elif spec.create_adapter_class is not None:
        # Non-polymorphic create forms render fields via
        # `field_for(schema, ...)` (reads `schema.model_fields`); the
        # spec's `create_adapter` is the TypeAdapter wrapper, so we bind
        # the underlying class instead.
        context["schema"] = spec.create_adapter_class

    if extras is not None:
        extras_kwargs = {
            "target": None,
            "request": request,
            "requesting_user": requesting_user,
        }
        if extra_kwargs:
            extras_kwargs.update(extra_kwargs)
        context.update(await extras(**extras_kwargs))

    return context


def make_new_form_handler(
    spec: EntitySpec,
    *,
    extras: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    extra_repos: tuple[tuple[str, type], ...] = (),
):
    return _make_factory_handler(
        spec,
        _NEW_FORM_SHAPE,
        handle_get_new_form,
        extras=extras,
        extra_repos=extra_repos,
    )


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

    context: dict[str, Any] = {
        "request": request,
        spec.name: target,
        "current_user": requesting_user,
    }
    if spec.can_write is not None:
        context["can_edit"] = spec.can_write(target, requesting_user)

    # Viewer-derived flags. `subject_attr` is the attribute on `target`
    # whose value equals `requesting_user.id` when the viewer IS the
    # subject — for `owner_attr=None` (users — the row IS the user), the
    # rule reduces to `target.id == viewer.id`; for owned resources
    # (provider, post), it uses the owner FK. The uniform rule lets every
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
    return _make_factory_handler(
        spec, _DETAIL_SHAPE, handle_detail, extras=extras, extra_repos=extra_repos
    )


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

    items, page_meta = paginate(items_plus_one, page=page_number, per_page=per_page)

    context: dict[str, Any] = {
        "request": request,
        spec.url_collection: items,
        "current_user": requesting_user,
        "can_admin_actions": is_admin(requesting_user),
        "page_meta": page_meta,
        "paginator_base_query": base_query(request),
    }
    # Filter echo — the list page's filter form preselects the active
    # value by reading ``selected_<name>`` from the context.
    for fname, fvalue in filter_values.items():
        context[f"selected_{fname}"] = fvalue
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
    else:
        context["search_url"] = None

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
    return _make_factory_handler(
        spec, _LIST_SHAPE, handle_list, extras=extras, extra_repos=extra_repos
    )
