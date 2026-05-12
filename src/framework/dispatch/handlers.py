"""Generic framework handlers driven by `EntitySpec`.

Phase 2 of #317 introduces generation: framework code reads from
`EntitySpec` and does the work that today is hand-written per-entity.
This module is the framework's home in the logic layer; the
underscore-prefix filename matches `_authz.py` (shared infrastructure
at the parent tier of `logic/`, importable from every cluster).

B1 (#326) adds `handle_delete` — the smallest verb. Subsequent
B-PRs will add `handle_create`, `handle_update`, etc., each following
the same shape: read knobs from the spec, perform the standard
ritual, delegate non-standard work back to the entity.

Entities with bespoke pre/post-rules keep their custom handlers and
do not call into here. The framework is for the *standard* shape;
custom shapes stay custom.
"""

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel

from src.domain.models import User
from src.framework.audit.core import mutate
from src.framework.audit.repository import AuditRepository
from src.framework.authz import is_admin
from src.framework.dispatch.entity_spec import EntitySpec
from src.framework.http.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.framework.persistence.base_repository import BaseRepository
from src.framework.rendering.projections import project_view


async def handle_delete(
    spec: EntitySpec,
    *,
    target_id: UUID,
    repo: BaseRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
    parent_id: UUID | None = None,
) -> None:
    """Generic delete handler driven by `spec`.

    Performs the standard delete ritual: load target → optional
    parent-FK verification + parent-existence load (owned subentities)
    → write_authz check → audited delete via `mutate(verb="delete")`.

    Reads from the spec:
      - `spec.model` — the SQLAlchemy class used to fetch the target
        (and parent, for owned subentities) via
        `repo.get_by_model_id`.
      - `spec.parent` — if set, the subentity convention is enforced:
        `parent_id` must be supplied, the child's FK column
        (`<parent.name>_id`) must equal `parent_id`, and the parent
        row must exist. `write_authz` runs against the parent (auth
        follows the ownership chain).
      - `spec.write_authz` — invoked against the target (top-level)
        or parent (subentity). `None` skips the check.
      - `spec.audit` — passed to `mutate(...)` as the resource binding.
        Required (delete must be audited).

    Entities with bespoke pre-delete rules (e.g. users' self-guard)
    keep their custom handlers and do not call this function.
    """
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
    requesting_user: User,
    parent_id: UUID | None = None,
) -> Any:
    """Generic create handler driven by `spec`.

    Performs the standard create ritual across three shapes:

    1. **Owned-subentity** (`spec.parent` set) — parent loaded,
       `write_authz` invoked against the parent, child instantiated
       from the payload's field dict, appended via
       `repo.add_child(parent, spec.url_collection, child)` so the
       parent's in-memory state stays coherent for the audit snapshot.
    2. **Polymorphic top-level** (`spec.discriminator` set) — the
       payload's discriminator value picks a `KindSpec` from the
       registry; the parent is instantiated with the discriminator
       column + owner, the detail row is built from
       `KindSpec.detail_fields`, and both persist in one flush via
       `repo.create_polymorphic`.
    3. **Standard top-level** — parent instantiated from the payload's
       field dict + owner column (when `spec.owner_attr` is set);
       persisted via `repo.create`.

    Across all three, the created row is wrapped in
    `mutate(verb="create")` so the audit row is captured and the
    transaction commits. Entities with bespoke create flows (e.g.
    providers' inline credential-list append) keep custom handlers.

    Reads from the spec:
      - `spec.audit` — required for the audit row.
      - `spec.parent` — picks the subentity path.
      - `spec.discriminator` — picks the polymorphic path.
      - `spec.write_authz` — invoked on parent for subentity creates.
        Top-level creates are gated only by the route's
        `write_user_dep` (no per-object check applies to a not-yet-
        created row).
      - `spec.owner_attr` — column on the parent set to
        `requesting_user.id` when not None.
      - `spec.model` — class instantiated for the parent.
      - `spec.url_collection` — name of the parent's relationship
        attribute for owned-subentity creates (convention).
    """
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
        child = spec.model(**payload.model_dump())
        created = await repo.add_child(parent, spec.url_collection, child)

    elif spec.discriminator is not None:
        kind = payload.kind
        kind_spec = spec.discriminator[kind]
        detail = kind_spec.detail_model(
            **{f: getattr(payload, f) for f in kind_spec.detail_fields}
        )
        parent_obj = spec.model(**{spec.discriminator.column: kind})
        if spec.owner_attr is not None:
            setattr(parent_obj, spec.owner_attr, requesting_user.id)
        created = await repo.create_polymorphic(
            parent_obj, detail, detail_relationship=kind_spec.detail_relationship
        )

    else:
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
        pass  # mutation already happened; `mutate` captures after-snapshot
    return created


async def handle_update(
    spec: EntitySpec,
    *,
    target_id: UUID,
    payload: BaseModel,
    repo: BaseRepository,
    audit_repo: AuditRepository,
    requesting_user: User,
    parent_id: UUID | None = None,
) -> Any:
    """Generic update handler driven by `spec`.

    Performs the standard update ritual: load target → optional
    parent-FK verification + write_authz → polymorphic kind-invariant
    check → audited patch via `mutate(verb="update")`.

    Three paths:

    1. **Owned-subentity** (`spec.parent` set) — parent loaded,
       FK matched against the child's persisted parent_id,
       `write_authz` on parent, partial-patch via `exclude_unset`.
    2. **Polymorphic** (`spec.discriminator` set) — payload's
       discriminator value must equal the target's persisted value
       (kind cannot change via PATCH); only the detail row is
       patched (parent's kind/owner_attr are immutable post-create);
       fields read from `kind_spec.detail_fields` (no `exclude_unset`
       — the schema's optionality is what makes the wire-shape work).
    3. **Standard top-level** — partial-patch via `exclude_unset`.

    All three audit via `mutate(verb="update")` so the audit row
    captures before/after snapshots and the transaction commits.

    Reads from the spec:
      - `spec.audit` — required.
      - `spec.parent` — picks the subentity path.
      - `spec.discriminator` — picks the polymorphic path; kind
        invariant enforced via `BadRequestError`.
      - `spec.write_authz` — invoked on target (top-level) or parent
        (subentity).
      - `spec.model` — target class.
    """
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
        update_fields = {f: getattr(payload, f) for f in kind_spec.detail_fields}
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


# --- Spec-driven factory infrastructure ---------------------------------
#
# Each `make_<verb>_handler` factory fabricates a callable with a typed
# signature so the route mount layer's introspection
# (`src/framework/dispatch/resource_routes.py`) can bind URL path params, body
# adapters, query filters, and `Depends` to the right handler kwargs.
# The six verbs (delete/create/update/edit_form/detail/list) used to be
# six near-identical 80-line factories — the differences are entirely
# *which* of the standard params each shape includes. `_FactoryShape`
# encodes that, and `_make_factory_handler` builds the signature +
# wrapper once. The six public factories below are thin wrappers that
# pair their `handle_*` function with a pre-baked shape.


@dataclass(frozen=True, slots=True)
class _FactoryShape:
    """Declarative shape of one verb's factory-built handler.

    `name_template` carries a single `{name}` placeholder filled with
    `spec.name` to produce the `__name__` (e.g. `_handle_delete_widget`).
    The booleans toggle which standard params appear in the
    synthesized signature and which kwargs the wrapper forwards to
    `handle_*(spec, ...)`.
    """

    name_template: str
    include_request: bool = False
    include_target_id: bool = False
    include_parent_id: bool = False
    include_payload: bool = False
    include_audit_repo: bool = False
    include_filters: bool = False
    accepts_extras: bool = False
    user_optional: bool = False
    # The new-form path doesn't load a target and has nothing to do
    # with `repo`, so the synthesized handler omits it; mount_form's
    # introspection only passes kwargs the handler declares.
    omit_repo: bool = False
    # Polymorphic entities' create-form takes `?kind=` as a query
    # param; when set, the synthesized handler declares `kind: str`
    # so the mount layer forwards it. Non-polymorphic entities ignore
    # this flag.
    include_kind_for_polymorphic: bool = False


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
)
_UPDATE_SHAPE = _FactoryShape(
    name_template="_handle_update_{name}",
    include_target_id=True,
    include_payload=True,
    include_parent_id=True,
    include_audit_repo=True,
)
_EDIT_FORM_SHAPE = _FactoryShape(
    name_template="_handle_get_{name}_edit_form",
    include_request=True,
    include_target_id=True,
)
_NEW_FORM_SHAPE = _FactoryShape(
    name_template="_handle_get_{name}_new_form",
    include_request=True,
    include_kind_for_polymorphic=True,
    omit_repo=True,
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
):
    """Build the wrapper that the mount layer will introspect + call.

    Walks `shape` to assemble the signature and the forwarding logic.
    `handler_fn` is the corresponding `handle_<verb>` to delegate to;
    `extras` / `extra_repos` are read by the detail/list shapes only.
    """
    id_param = spec.id_param
    parent_id_param = spec.parent.id_param if spec.parent is not None else None
    filter_names = (
        tuple(qp.name for qp in spec.filters) if shape.include_filters else ()
    )
    extra_repo_names = tuple(name for name, _ in extra_repos)

    sig_params: list[inspect.Parameter] = []
    if shape.include_request:
        sig_params.append(_param("request", Request))
    if shape.include_parent_id and parent_id_param is not None:
        sig_params.append(_param(parent_id_param, UUID))
    if shape.include_target_id:
        sig_params.append(_param(id_param, UUID))
    if shape.include_filters:
        for qp in spec.filters:
            sig_params.append(_param(qp.name, qp.annotation))
    if shape.include_payload:
        sig_params.append(_param("payload", BaseModel))
    if shape.include_kind_for_polymorphic and spec.discriminator is not None:
        sig_params.append(_param("kind", str))
    if not shape.omit_repo:
        sig_params.append(_param("repo", BaseRepository))
    if shape.include_audit_repo:
        sig_params.append(_param("audit_repo", AuditRepository))
    user_ann = User | None if shape.user_optional else User
    sig_params.append(_param("requesting_user", user_ann))
    for name, repo_type in extra_repos:
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
        return await handler_fn(spec, **call_kwargs)

    _handler.__signature__ = inspect.Signature(parameters=sig_params)  # type: ignore[attr-defined]
    _handler.__name__ = shape.name_template.format(name=spec.name)
    _handler.__qualname__ = _handler.__name__
    return _handler


def make_delete_handler(spec: EntitySpec):
    """Build a `mount_delete`-compatible handler from `spec`.

    Synthesizes a typed signature that `mount_delete`'s introspection
    recognizes (id param + parent id for subentities, plus `repo`,
    `audit_repo`, `requesting_user`) and delegates to
    `handle_delete(spec, ...)`. The wrapper's `__name__` is
    `_handle_delete_<spec.name>` so stack traces stay readable; route
    files assign the result to that module-level attribute so
    contract-test patches against `<routes module>._handle_delete_<entity>`
    flow through the mount layer's `_resolve_handler`.
    """
    return _make_factory_handler(spec, _DELETE_SHAPE, handle_delete)


def make_create_handler(spec: EntitySpec):
    """Build a `mount_create`-compatible handler from `spec`.

    Synthesized parameters: `parent_id` (subentities only), `payload`,
    `repo`, `audit_repo`, `requesting_user`. Delegates to
    `handle_create(spec, ...)`; the framework dispatches by
    `payload.kind` when `spec.discriminator` is set.
    """
    return _make_factory_handler(spec, _CREATE_SHAPE, handle_create)


def make_update_handler(spec: EntitySpec):
    """Build a `mount_update`-compatible handler from `spec`.

    Synthesized parameters: `parent_id` (subentities only), the
    target's id from the URL, `payload`, `repo`, `audit_repo`,
    `requesting_user`. Delegates to `handle_update(spec, ...)`.
    """
    return _make_factory_handler(spec, _UPDATE_SHAPE, handle_update)


async def handle_get_edit_form(
    spec: EntitySpec,
    *,
    request: Request,
    target_id: UUID,
    repo: BaseRepository,
    requesting_user: User,
) -> dict[str, Any]:
    """Generic edit-form handler driven by `spec`.

    Performs: load target → 404 → write_authz → return template context
    binding the entity under `spec.name` (so existing templates' variable
    names — `provider`, `post` — keep working without per-entity glue).

    For polymorphic entities (`spec.discriminator` set), returns
    `template_name` in the context using `kind_spec.edit_template` so
    `mount_form`'s template precedence renders the per-kind edit page.
    Entities with bespoke edit-form rules keep custom handlers.

    Reads from the spec:
      - `spec.model` — class fetched via `repo.get_by_model_id`.
      - `spec.write_authz` — invoked against the target. `None` skips
        the gate (matches the `handle_update`/`handle_delete` shape).
      - `spec.discriminator` — if set, populates `template_name` from
        the discriminator-registry entry's `edit_template` attribute.
      - `spec.static_context` — merged in for entities that declare
        constants the form template reads (e.g. provider enum labels).
    """
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
    return context


def make_edit_form_handler(spec: EntitySpec):
    """Build a `mount_form(on_existing=True)`-compatible handler from `spec`.

    Synthesized parameters: `request`, the target's id from the URL,
    `repo`, `requesting_user`. Delegates to
    `handle_get_edit_form(spec, ...)`.
    """
    return _make_factory_handler(spec, _EDIT_FORM_SHAPE, handle_get_edit_form)


async def handle_get_new_form(
    spec: EntitySpec,
    *,
    request: Request,
    requesting_user: User,
    kind: str | None = None,
) -> dict[str, Any]:
    """Generic create-form handler driven by `spec`.

    Returns a template context with `request`, `current_user`, and any
    `spec.static_context` constants the form template reads (enum
    labels, etc.). For non-polymorphic entities the create-adapter is
    bound under `schema` so templates using `field_for(schema, ...)`
    keep working without per-entity glue. For polymorphic entities
    (`spec.discriminator` set), `template_name` is populated from the
    discriminator-registry entry's `create_template` so `mount_form`'s
    template precedence renders the per-kind create page; the
    `?kind=` query param picks the entry, defaulting to the first
    registered kind.
    """
    context: dict[str, Any] = {
        "request": request,
        "current_user": requesting_user,
    }
    if spec.static_context:
        context.update(spec.static_context)
    if spec.discriminator is not None:
        chosen = kind or spec.discriminator.names[0]
        context["template_name"] = spec.discriminator[chosen].create_template
    elif spec.create_adapter_class is not None:
        # Non-polymorphic create forms render fields via
        # `field_for(schema, ...)` (reads `schema.model_fields`); the
        # spec's `create_adapter` is the TypeAdapter wrapper, so we bind
        # the underlying class instead.
        context["schema"] = spec.create_adapter_class
    return context


def make_new_form_handler(spec: EntitySpec):
    """Build a `mount_form(on_existing=False)`-compatible handler from `spec`.

    Synthesized parameters: `request`, `requesting_user`, plus
    `kind: str` for polymorphic entities (forwarded as the
    `?kind=` query param). Delegates to `handle_get_new_form(spec, ...)`.
    """
    return _make_factory_handler(spec, _NEW_FORM_SHAPE, handle_get_new_form)


async def handle_detail(
    spec: EntitySpec,
    *,
    request: Request,
    target_id: UUID,
    repo: BaseRepository,
    requesting_user: User | None,
    extras: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    extra_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generic detail handler driven by `spec`.

    Performs: load target → 404 → compute `can_edit` from
    `spec.can_write` (when set) → inject viewer-derived flags +
    `target_<name>` projection from spec metadata → merge
    entity-specific extras via the callable hook. The base context binds
    the entity under `spec.name` (e.g. `"post"`, `"provider"`) so
    existing templates that read `{{ post }}` / `{{ provider }}` keep
    working without per-entity glue.

    Viewer-derived keys, always injected before extras run:
      - `is_self` — viewer is the subject (`target.<owner_attr or 'id'>
        == requesting_user.id`).
      - `can_admin_actions` — `is_admin(viewer) and not is_self`.
      - `can_view_private` — when `spec.private_field_predicate` is set,
        the predicate evaluated against `(viewer, target)`.
      - `target_<name>` — when `spec.public_fields` is set, a
        `project_view` dict with private fields gated by the predicate.
      - Entries from `spec.static_context` — spec-declared constants
        (registry tuples, enum lists) merged before extras so the
        callable can still override.

    `extras` is the entity's per-detail customization callable. It
    receives the loaded target plus `request`, `requesting_user`, and
    any keyword args in `extra_kwargs` (the route layer passes typed
    repos this way — e.g. `user_favorite_repo` for provider detail).
    The dict it returns is merged into the base context with
    last-write-wins semantics; entities can override any framework-
    injected key.

    Reads from the spec:
      - `spec.model` — class fetched via `repo.get_by_model_id`.
      - `spec.can_write` — when set, populates `can_edit` in context.
        Always accepts `User | None`; entities whose detail page is
        public (`read_user_dep=None`) pass `requesting_user=None`.
      - `spec.owner_attr` — drives the `is_self` comparison.
      - `spec.private_field_predicate` — drives `can_view_private` and
        gates the `target_<name>` projection.
      - `spec.public_fields` — declares the projection shape.
    """
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
    """Build a `mount_detail`-compatible handler from `spec`.

    Synthesized parameters: `request`, the target's id from the URL,
    `repo`, `requesting_user: User | None`, plus one parameter per
    `extra_repos` entry. Delegates to `handle_detail(spec, ...)` with
    the `extras` callable passed through and `extra_repos` collected
    into `extra_kwargs`.
    """
    return _make_factory_handler(
        spec, _DETAIL_SHAPE, handle_detail, extras=extras, extra_repos=extra_repos
    )


async def handle_list(
    spec: EntitySpec,
    *,
    request: Request,
    repo: BaseRepository,
    requesting_user: User | None,
    filter_values: dict[str, Any],
    extras: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    extra_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generic list handler driven by `spec`.

    Calls ``getattr(repo, f"list_{spec.url_collection}")(**filter_values)``
    — the per-entity repo method whose name is fixed by convention.
    Returns the standard list-page context: ``request``, ``current_user``,
    the items bound under ``spec.url_collection`` (e.g. ``"providers"``),
    and a ``selected_<name>`` echo for each filter value so the filter
    form can preselect the active selection.

    ``can_admin_actions`` is auto-injected from
    ``is_admin(requesting_user)`` — list-level templates that show
    admin-only actions read it without per-entity glue. When the spec
    sets ``list_exclude_self=True``, the viewer is dropped from the
    result set by passing ``exclude_self=requesting_user`` to the repo
    method (the repo method must accept that kwarg; anonymous viewers
    skip the filter and see the full list). Entries from
    ``spec.static_context`` (constants like posts' ``post_kinds`` tuple)
    merge into the context after the filter echo and before extras.

    ``extras`` is the per-entity post-fetch customization hook (matches
    ``handle_detail``'s ``extras`` shape). It receives ``items``,
    ``request``, ``requesting_user``, ``filter_values``, plus any
    ``extra_kwargs``. Its returned dict merges into the context with
    last-write-wins semantics; entities can override any framework-
    injected key.

    Reads from the spec:
      - ``spec.url_collection`` — picks the repo method name and the
        context key for the items list.
      - ``spec.list_exclude_self`` — when True, drops the viewer from
        the result set via the repo method's ``exclude_self`` kwarg.
      - ``spec.list_order_by`` — column expression for the framework
        default (``BaseRepository.list_default``); used when the repo
        has no bespoke ``list_<collection>`` method.

    Dispatch: prefers ``repo.list_<collection>(**filter_values)`` when
    that method exists on the repo (entities with joins / custom
    filters like providers). Otherwise falls through to
    ``repo.list_default(spec.model, order_by=spec.list_order_by, ...)``
    so trivial list-by-creation-time / list-by-name entities don't
    need a per-entity wrapper.
    """
    list_kwargs: dict[str, Any] = dict(filter_values)
    if spec.list_exclude_self and requesting_user is not None:
        list_kwargs["exclude_self"] = requesting_user
    list_method = getattr(repo, f"list_{spec.url_collection}", None)
    if list_method is not None:
        items = await list_method(**list_kwargs)
    else:
        if spec.list_order_by is None:
            raise ValueError(
                f"handle_list: spec {spec.name!r} has no list_order_by and "
                f"no bespoke list_{spec.url_collection!s} method on the "
                "repo — either declare list_order_by on the spec or add a "
                f"list_{spec.url_collection!s}() method to the repo."
            )
        items = await repo.list_default(
            spec.model, order_by=spec.list_order_by, **list_kwargs
        )

    context: dict[str, Any] = {
        "request": request,
        spec.url_collection: items,
        "current_user": requesting_user,
        "can_admin_actions": is_admin(requesting_user),
    }
    # Filter echo — the list page's filter form preselects the active
    # value by reading ``selected_<name>`` from the context.
    for fname, fvalue in filter_values.items():
        context[f"selected_{fname}"] = fvalue

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
    """Build a `mount_list`-compatible handler from `spec`.

    Synthesized parameters: `request`, one parameter per
    `spec.filters` entry, `repo`, `requesting_user: User | None`, and
    one parameter per `extra_repos` entry. Delegates to
    `handle_list(spec, ...)` with the filter values collected into
    `filter_values` and `extra_repos` collected into `extra_kwargs`.
    """
    return _make_factory_handler(
        spec, _LIST_SHAPE, handle_list, extras=extras, extra_repos=extra_repos
    )
