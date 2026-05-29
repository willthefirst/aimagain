# Dispatch: specs → routes

Turns an `EntitySpec` declaration into a working HTTP route surface.

## The pipeline

```
EntitySpec (read-only)
   ↓ resource_routes.mount_entity(router, ENTITY, handlers={...})
   ↓
   ↓ for each opted-in verb in spec.routes / spec.state_axes / spec.subresources:
   ↓   ├── if explicit handler supplied → bind it
   ↓   └── else → make_<verb>_handler(ENTITY) factory builds one
   ↓
   ↓ stitch factory-built handlers onto the caller module as
   ↓ `_handle_<verb>_<entity>` (for contract-test patching)
   ↓
FastAPI route registered, with FastAPI Depends synthesized from the
handler's annotated parameters (repos via the persistence registry,
auth via spec.read_user_dep / write_user_dep, query params via the
mount's query_params= tuple).
```

## Files

- `entity_spec.py` — `EntitySpec` dataclass + supporting types (`StateAxis`, `RouteSet`, `Templates`, `EdgeAudit`, `AuthDeps`, `AuthzPolicy`, `M2NRelation`, `RelatedListSubresource`, `Redirects`). The spec is the single declaration the rest of the codebase reads from. `to_resource_spec()` bridges to the mount helpers.
- `mounts/` — the `mount_entity` dispatcher and the per-verb `mount_*` family, one file per verb. See [`mounts/README.md`](mounts/README.md) for the file-by-file layout. The `ResourceSpec` dataclass `mount_entity` constructs internally from the upstream `EntitySpec` lives at `mounts/_spec.py`. Per-mount docstrings document required spec fields and handler signatures.
- `resource_routes.py` — re-export shim that lifts the public surface (`mount_entity`, the `mount_*` family, `ResourceSpec`, `QueryParam`, `MountError`) out of `mounts/` so external imports of `src.framework.dispatch.resource_routes` keep working.
- `handlers.py` — generic CRUD handlers (`handle_create`, `handle_update`, `handle_delete`, `handle_detail`, `handle_list`) and the `make_<verb>_handler(spec)` factories that build callables with synthesized signatures so `mount_*`'s introspection wires the right deps.
- `filters.py` — declarative filter types (`Filter` base, `TextFilter`, `ChoiceFilter`, `FlagFilter`) that an entity declares on `EntitySpec.filters`. Each carries both the URL contract (`name`, `annotation`, `default` — bridged to `QueryParam` via `to_query_param()` so FastAPI sees a normal `Query(...)` param) and UI metadata (`kind`, `label`, `placeholder`, `choices`, `multi`). Every declared `Filter` renders as a form control on the dedicated `/<collection>/search` page (`views/search.html`); the list-page toolbar carries only the "Filter · N" link (left) and the page-action menu (right). Active values appear as removable tags in the active-filter strip below the toolbar. Raw `QueryParam` entries on `EntitySpec.filters` still work (URL-only, no UI); `Filter` is layered on top, not a replacement.
- `pagination.py` — `Page` snapshot dataclass + `parse_page` / `offset_for` / `paginate` / `base_query` helpers consumed by `handle_list` and the bespoke list handlers (`handle_list_my_favorites`, `handle_list_user_clinicians`). Reads `?page=N` from the request, asks the logic layer for `per_page + 1` rows, slices the probe off to compute `has_next` without a `COUNT(*)`. `DEFAULT_PAGE_SIZE = 25`; per-entity override via `EntitySpec.page_size`. The view-type template `views/list.html` renders the `_shared/pagination.html` footer automatically from the `page_meta` context var; pages where the result fits on a single page emit nothing.
- `base_router.py` — thin `APIRouter` wrapper that applies the framework's common decorators (`handle_route_errors`, logging) and the per-entity router factory `make_entity_router(spec)`.

## Two declarations, one source of truth

`EntitySpec` (this directory) and `ResourceSpec` (also this directory) look similar but serve different layers. `EntitySpec` is the **upstream declaration** every consumer reads from. `ResourceSpec` is the **downstream input** to the mount helpers — derived from `EntitySpec` via `to_resource_spec()` at mount time. Future cross-cutting features (richer audit hooks, response synthesis, OpenAPI doc generation) add fields to `EntitySpec`; `ResourceSpec` stays narrow because it only needs what the mount helpers consume.

## Write-time authorization: `write_authz` vs. `payload_authz`

Two distinct spec hooks gate writes, run in this order from
`handle_create` / `handle_update`:

- **`write_authz`** (on `EntitySpec`) — gates **the target row**. Runs
  after the parent or target has been loaded. For owned subentities,
  the predicate sees the parent; for top-level entities, it sees the
  target. Raises `ForbiddenError` on rejection. Same callable is used
  by `handle_delete` and `handle_get_edit_form`.

- **`payload_authz_path`** (on `EntitySpec`) — gates **rows the
  payload references** (e.g. "the user must own the Org the payload's
  `org_id` points at"). Runs *after* `write_authz`, *before* the model
  is built / patched. The dotted-string path resolves via `importlib`
  at mount time; the framework synthesizes typed-repo kwargs from
  `payload_authz_repos` and forwards them to the callable. Raises
  `ForbiddenError` / `NotFoundError` on rejection.

The two run in addition to each other, not instead of. Superuser
bypass is the **callable's responsibility** — the framework does not
short-circuit on `requesting_user.is_superuser`. Each hook owns its
own policy (e.g. clinicians' Org-attach rule lets superusers attach
to any Org, but a different rule might not).

Declaring `payload_authz_path` alongside an explicit `handlers["create"]`
or `handlers["update"]` is rejected at mount time — the explicit
handler would silently bypass the spec hook. Use one or the other.

## Handler stitching

`mount_entity` walks up the call stack to find the route module that invoked it and `setattr`s factory-built handlers onto it as `_handle_<verb>_<entity>`. This keeps the contract-test patch path stable across the refactor that moved handler bodies out of route files. The stitching is described in the docstring of `_detect_caller_module` in `mounts/entity.py`.

## Tests

Colocated `test_*.py`: spec correctness (`test_entity_spec.py`), each mount helper's URL shape and signature synthesis (`test_resource_routes.py`), generic handler behavior (`test_handlers.py`), the `BaseRouter` wrapper (`test_base_router.py`).
