"""Small helpers shared across the per-verb mount modules.

Lives below the per-verb files in the dependency graph: each
`mount_<verb>.py` imports from here, but nothing in here imports a
specific verb module. Keeps the package free of cycles.
"""

from typing import Any, Awaitable, Callable
from uuid import UUID

from src.framework.dispatch.mounts._spec import QueryParam, ResourceSpec


def normalize_filters(filters: tuple[Any, ...]) -> tuple[QueryParam, ...]:
    """Map each ``EntitySpec.filters`` entry to its ``QueryParam`` shape.

    ``Filter`` instances carry UI metadata on top of the URL contract;
    the mount layer only needs the URL side, so we call
    ``to_query_param()`` on each. Raw ``QueryParam`` entries (the
    legacy shape) pass through unchanged.

    Kept local to this package so ``Filter`` stays an entity_spec-side
    import — the route-mount layer just consumes a uniform tuple.
    """
    from src.framework.dispatch.filters import Filter

    return tuple(f.to_query_param() if isinstance(f, Filter) else f for f in filters)


def walk_parent_chain(spec: ResourceSpec) -> list[ResourceSpec]:
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


def path_segments_under_router(spec: ResourceSpec, *, with_id: bool) -> str:
    """Build the route path *relative to the router's prefix*.

    The router's prefix is expected to be the topmost ancestor's
    collection (e.g. ``APIRouter(prefix="/clinicians")`` for both
    clinician routes and licensure-under-clinician routes). This function
    produces the rest:

    ``/{clinician_id}/licensures`` (no id) or
    ``/{clinician_id}/licensures/{licensure_id}`` (with id) for a
    licensure spec whose parent is the clinician spec.

    For a top-level spec (no parent), returns ``""`` (no id) or
    ``/{spec.id_param}`` (with id).
    """
    chain = walk_parent_chain(spec)
    # chain[0] is topmost ancestor; its collection is the router prefix.
    # Each subsequent entry contributes /{parent.id_param}/{this.collection}.
    parts: list[str] = []
    for child in chain[1:]:
        assert child.parent is not None
        parts.append(f"/{{{child.parent.id_param}}}/{child.collection}")
    if with_id:
        parts.append(f"/{{{spec.id_param}}}")
    return "".join(parts)


def parent_path_param_pairs(spec: ResourceSpec) -> tuple[tuple[str, type], ...]:
    """All parent id-params (excluding ``spec.id_param``) the route binds.

    For a licensure spec under clinician, returns ``(("clinician_id", UUID),)``.
    For a top-level spec, returns ``()``.
    """
    out: list[tuple[str, type]] = []
    s: ResourceSpec | None = spec.parent
    while s is not None:
        out.append((s.id_param, UUID))
        s = s.parent
    out.reverse()
    return tuple(out)


def resolve_dotted_path(entity: Any, dotted_path: str, field_label: str) -> Any:
    """Import `pkg.module.attr` lazily and return the attribute.

    Used by `resolve_spec_bound_handler` (state-axis / subresource
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


def resolve_handler(fn: Callable[..., Any]) -> Callable[..., Any]:
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


def resolve_spec_bound_handler(
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
        return resolve_dotted_path(entity, handler_path, key)
    raise KeyError(
        f"mount_entity({entity.name!r}): no handler for {key!r} — "
        f"supply it in `handlers={{{key!r}: ...}}` or set "
        "`handler_path=` on the spec entry."
    )


async def call_handler_with(
    handler: Callable[..., Any],
    handler_kwarg_names: list[str],
    kwargs: dict[str, Any],
) -> Any:
    """Call `handler` with the subset of `kwargs` matching the
    introspected handler kwarg names. Goes through `resolve_handler` so
    test monkey-patching against the handler's home module takes effect.
    """
    handler_kwargs = {
        name: kwargs[name] for name in handler_kwarg_names if name in kwargs
    }
    return await resolve_handler(handler)(**handler_kwargs)


# Verbs `mount_entity` auto-binds factory-built handlers for when the
# entity opts into them but the caller didn't supply an explicit handler.
TOP_LEVEL_AUTO_BIND_VERBS: tuple[str, ...] = (
    "list",
    "detail",
    "create",
    "update",
    "delete",
    "form_edit",
    "form_new",
)


def owned_factory_makers() -> dict[str, Callable[..., Callable[..., Awaitable[Any]]]]:
    """Lazy-import the generic CRUD-framework factories for owned subentities.

    Imported on demand to avoid a module-import cycle: this package is
    imported by ``src.framework.dispatch.entity_spec`` (for
    ``ResourceSpec`` and ``QueryParam``), and ``src.framework.dispatch.
    handlers`` imports ``EntitySpec``. Doing the import inside
    ``mount_entity``'s owned-subentity branch breaks the cycle — by the
    time we reach this code at runtime, the logic module has finished
    initializing.

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
