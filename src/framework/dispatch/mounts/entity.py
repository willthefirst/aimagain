"""`mount_entity` — the spec-driven dispatcher.

Reads `EntitySpec` opt-ins (routes, state axes, subresources,
discriminator, etc.) and calls the appropriate per-verb mount
helpers. Each helper stays unchanged; `mount_entity` is dispatch
glue + auto-binding of factory-built handlers + cross-cutting
mount-time validation.
"""

import sys
from typing import Any, Awaitable, Callable

from src.framework.dispatch.mounts._common import (
    TOP_LEVEL_AUTO_BIND_VERBS,
    normalize_filters,
    owned_factory_makers,
    resolve_dotted_path,
    resolve_spec_bound_handler,
)
from src.framework.dispatch.mounts._spec import QueryParam
from src.framework.dispatch.mounts.state_axis import _wrap_state_axis_with_self_guard

# `mount_entity` looks up the per-verb mount functions through the
# re-export shim (`resource_routes`) at call time rather than capturing
# them at import time. That keeps the long-standing test pattern
# `import src.framework.dispatch.resource_routes as rr;
#  rr.mount_list = stub` working — patches against the shim's namespace
# are honored on each dispatch. Resolved lazily inside `mount_entity`
# because the shim imports this module (the cycle is safe at call time
# but not at import time).


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
    owned_subentities: tuple[Any, ...] | None = None,
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
    from src.framework.dispatch import resource_routes as _rr

    spec = entity.to_resource_spec()
    if handlers is None:
        handlers = {}
    # Default to the spec's `children` tuple — every subentity that
    # declared `parent=<this>` at construction time is already in
    # `entity.children` (see `EntitySpec.__post_init__`), so route
    # files don't need to list them twice. Callers can still pass
    # an explicit tuple (e.g. `()` to mount only the parent, or a
    # subset for staged rollouts).
    if owned_subentities is None:
        owned_subentities = entity.children

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
        resolve_dotted_path(entity, entity.detail_extras_path, "detail_extras_path")
        if entity.detail_extras_path is not None
        else None
    )
    list_extras = (
        resolve_dotted_path(entity, entity.list_extras_path, "list_extras_path")
        if entity.list_extras_path is not None
        else None
    )
    form_extras = (
        resolve_dotted_path(entity, entity.form_extras_path, "form_extras_path")
        if entity.form_extras_path is not None
        else None
    )
    payload_authz = (
        resolve_dotted_path(entity, entity.payload_authz_path, "payload_authz_path")
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
    module = _detect_caller_module()
    factory_makers = owned_factory_makers()
    mod = sys.modules[module]

    auto_bound: dict[str, Callable[..., Awaitable[Any]]] = {}
    for verb in TOP_LEVEL_AUTO_BIND_VERBS:
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
        if verb not in TOP_LEVEL_AUTO_BIND_VERBS:
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
        _rr.mount_list(
            router,
            spec,
            handler=effective_handlers["list"],
            query_params=normalize_filters(entity.filters),
        )
        consumed.add("list")
    if entity.routes.create:
        _rr.mount_create(router, spec, handler=effective_handlers["create"])
        consumed.add("create")
    if entity.routes.form_new:
        query_params: tuple[QueryParam, ...] = ()
        if entity.discriminator is not None and entity.discriminator_value is None:
            # Polymorphic supertype's create-form `?kind=` query param
            # derives its Literal universe from the discriminator
            # registry — single source of truth for the kind names.
            # Default is `None`, which lets the handler render the
            # picker template (`spec.form_template`) when no kind is
            # specified, rather than silently defaulting to the first
            # registered kind.
            #
            # Subset-supertype faces (`discriminator_values` set) narrow
            # the Literal to their declared subset — `/openings/form?kind=
            # referral` 422s at the FastAPI param layer rather than
            # reaching the handler.
            #
            # Kind-locked faces (`discriminator_value` set) skip this
            # synthesis — there's no picker on a single-kind URL family;
            # the form goes straight to the kind-specific create page.
            from typing import Literal, Optional

            names = (
                entity.discriminator_values
                if entity.discriminator_values is not None
                else entity.discriminator.names
            )
            query_params = (QueryParam("kind", Optional[Literal[*names]], None),)
        _rr.mount_form(
            router,
            spec,
            handler=effective_handlers["form_new"],
            template=entity.templates.form_new,
            query_params=query_params,
        )
        consumed.add("form_new")
    if entity.routes.form_edit:
        _rr.mount_form(
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
        _rr.mount_search(router, entity, template=entity.templates.search)
    if entity.routes.detail:
        _rr.mount_detail(
            router,
            spec,
            handler=effective_handlers["detail"],
            singleton_alias=entity.singleton_alias,
        )
        consumed.add("detail")
    if entity.routes.update:
        _rr.mount_update(router, spec, handler=effective_handlers["update"])
        consumed.add("update")
    if entity.routes.delete:
        _rr.mount_delete(router, spec, handler=effective_handlers["delete"])
        consumed.add("delete")

    for axis in entity.state_axes:
        handler = resolve_spec_bound_handler(
            entity, effective_handlers, key=axis.name, handler_path=axis.handler_path
        )
        if axis.forbid_self:
            handler = _wrap_state_axis_with_self_guard(
                handler, id_param=spec.id_param, axis_name=axis.name
            )
        _rr.mount_state_axis(
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
        handler = resolve_spec_bound_handler(
            entity, effective_handlers, key=key, handler_path=sub.handler_path
        )
        _rr.mount_related_list(
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
    factory_makers = owned_factory_makers() if owned_subentities else {}
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
