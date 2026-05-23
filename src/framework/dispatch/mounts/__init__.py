"""Per-verb split of the route-mount machinery.

`src.framework.dispatch.resource_routes` re-exports the public surface
(`mount_entity`, the `mount_*` family, `ResourceSpec`, `QueryParam`,
`MountError`) from this package so external imports keep working.

Each verb lives in its own module:

- `delete.py`, `detail.py`, `list_.py`, `form.py`, `create.py`,
  `update.py`, `state_axis.py`, `related_list.py`, `search.py`,
  `edge.py` — one `mount_*` function each.
- `entity.py` — the `mount_entity` orchestrator that reads an
  `EntitySpec`'s opt-ins and calls the per-verb mounts.

Shared infrastructure:

- `_spec.py` — `QueryParam` and `ResourceSpec` dataclasses.
- `_synth.py` — signature-synthesis machinery (`_synthesize_route_fn`,
  `_SynthOptions`, `_call_handler_with`, `MountError`).
- `_common.py` — small helpers shared across the per-verb modules
  (path building, parent walks, dotted-path resolution, the
  `_resolve_handler` test-patch indirection).
"""
