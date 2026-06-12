# `mounts/`: per-verb split of the route-mount machinery

One file per HTTP-shaped verb so each mount sits on a screen. The
public surface (`mount_entity`, every `mount_*`, `ResourceSpec`,
`QueryParam`, `MountError`) is re-exported by
[`../resource_routes.py`](../resource_routes.py) so external callers
keep their existing import path.

## Files

Per-verb modules (each defines exactly one `mount_*` function):

- `delete.py` — `DELETE /<collection>/{id}`
- `detail.py` — `GET /<collection>/{id}`
- `list_.py` — `GET /<collection>` (underscored to avoid shadowing the
  built-in `list`). For parent-owned specs, mounts the prefixed shape
  `GET /<parent>/{parent_id}/<collection>` automatically — the bespoke
  `list_<collection>` repo method must accept the parent id under
  `spec.parent.id_param` to scope the listing.
- `form.py` — `GET /<collection>/form` and `GET /<collection>/{id}/form`.
  For parent-owned specs, mounts the prefixed shape
  `GET /<parent>/{parent_id}/<collection>/form` (and the edit-form
  counterpart). Both `resource_url` and `resource_detail_url` in the
  rendered template context walk the parent chain.
- `create.py` — `POST /<collection>`
- `update.py` — `PATCH /<collection>/{id}`
- `state_axis.py` — `PUT /<collection>/{id}/<axis>`. Also home to
  `_wrap_state_axis_with_self_guard` (the `forbid_self=True` wrapper
  `mount_entity` applies — re-exported by `resource_routes.py`
  because contract tests patch it by its old path).
- `edge.py` — the three self-only routes for an M:N edge entity
  (`GET ""`, `POST /{to_attr}`, `DELETE /{to_attr}`).
- `related_list.py` — `GET /<parent>/{parent_id}/<child>`
- `search.py` — `GET /<collection>/search`
- `entity.py` — `mount_entity`, the spec-driven dispatcher that reads
  `EntitySpec` opt-ins and calls the per-verb mounts. Also home to
  `_detect_caller_module` because the stack-walk relies on living in
  the same module as `mount_entity` (so frames inside this file are
  the ones being skipped past).

Shared infrastructure:

- `_spec.py` — `QueryParam` and `ResourceSpec` dataclasses + the
  module-private `_UNSET` sentinel used by `QueryParam.required()`.
- `_synth.py` — `synthesize_route_fn`, `SynthOptions`, `MountError`,
  and the type-inspection helpers. Every per-verb mount calls
  `synthesize_route_fn(handler=…, spec=…, options=…, response_builder=…)`
  to turn the handler's typed signature into a FastAPI-visible route
  function.
- `_common.py` — small helpers shared across the per-verb modules:
  `path_segments_under_router`, `parent_path_param_pairs`,
  `walk_parent_chain`, `normalize_filters`, `resolve_dotted_path`,
  `resolve_handler`, `resolve_spec_bound_handler`,
  `call_handler_with`, `owned_factory_makers`, the
  `TOP_LEVEL_AUTO_BIND_VERBS` constant, `subresource_breadcrumb_items`
  (the single producer of the 3-step `_breadcrumb_items` —
  collection → parent row → child label, with the collection segment's
  lock reason sourced from `entity_lock_reason(parent_spec.name,
  viewer)`), and `ParentBreadcrumbPlumbing` (the single handshake
  that wires `_breadcrumb_items` into each parent-owned mount —
  `mount_list`, `mount_form`, `mount_related_list`). `mount_edge_routes`
  emits the same shape via a different code path because its parent
  row is the requesting user with no PK lookup.

## Dependency direction

`_spec.py` is the leaf — nothing in this package imports from a verb
file. `_synth.py` depends on `_spec.py`. `_common.py` depends on
`_spec.py`. Per-verb files depend on `_spec.py`, `_synth.py`, and
(if they need path/parent helpers) `_common.py`. `entity.py` depends
on everything else.
