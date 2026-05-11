# API common: Shared utilities and standardized patterns

The `api/common/` directory contains **shared utilities** for the API layer, implementing standardized patterns for error handling, logging, response formatting, and route management that ensure consistency across all API endpoints.

## Core philosophy: Standardized API patterns

Common utilities provide **consistent behavior** across all API routes through decorators, response helpers, and error handling patterns that eliminate boilerplate and ensure uniform user experience.

### What we do

- **Standardized error handling**: Pass through `HTTPException` subclasses raised by logic handlers; translate fastapi-users exceptions; convert anything unexpected into a 500
- **Automatic logging**: Structured logging for all route calls with entry/exit/error tracking
- **Response formatting**: Consistent JSON and HTML response structures
- **BaseRouter wrapper**: Automatic application of common decorators and configurations
- **API exception classes**: Reusable `APIException` subclasses (`NotFoundError`, `ForbiddenError`, etc.) that logic handlers raise directly

**Example**: BaseRouter automatically applies error handling and logging:

```python
from src.api.common import BaseRouter

# Create router with automatic decorators
users_router_instance = APIRouter()
router = BaseRouter(router=users_router_instance)

@router.get("/users")  # Automatically gets error handling + logging
async def list_users():
    return await handle_list_users()  # Errors auto-mapped to HTTP
```

### What we don't do

- **Business logic**: Common utilities only handle cross-cutting concerns, not domain logic
- **Data validation**: Pydantic schemas handle request/response validation
- **Authentication**: Authentication logic stays in auth layer
- **Route-specific logic**: Common code stays generic and reusable

**Example**: Don't put business logic in common utilities:

```python
# Bad - business logic in common utility
def create_user_response(user):
    # Business logic about user formatting
    if user.is_admin:
        return {"status": "admin", "data": {...}}

# Good - generic response formatting only (see responses.py)
def created_response(*, id, location, hx_redirect=None) -> JSONResponse:
    return JSONResponse(
        status_code=201,
        content={"id": str(id)},
        headers={"Location": location, "HX-Redirect": hx_redirect or location},
    )
```

## Architecture: Cross-cutting concerns layer

**Routes -> Common Utilities -> Logic Layer**

Common utilities handle concerns that span multiple routes and domains.

## Common utilities responsibility matrix

| Utility         | Purpose                | Responsibilities                                                | Used By                  |
| --------------- | ---------------------- | --------------------------------------------------------------- | ------------------------ |
| **BaseRouter**  | Route standardization  | Apply decorators, manage dependencies                           | All route files          |
| **responses**   | Response formatting    | `APIResponse.html_response` for templates; module-level `created_/updated_/deleted_/refreshed_response` for HTMX-aware mutations | All route handlers       |
| **Decorators**  | Cross-cutting concerns | Error handling, logging                                         | BaseRouter (automatic)   |
| **Exceptions**  | Error vocabulary       | API exception classes raised by logic; fastapi-users translator | Logic handlers, decorator |
| **Forms**       | Form-encoded request glue | `parse_form_to_payload` and `validate_or_422`                | Route handlers that accept form-encoded bodies |
| **projections** | View-projection with field-level visibility | `project_view(obj, public_fields, actor, private_fields, private_field_predicate)` — gate fields per viewer | Handlers building per-viewer response dicts (user detail today) |
| **resource_routes** | Unified `ResourceSpec` grammar | Declare a resource once, opt into the operations to expose via `mount_*`; sub-resources nest via `parent=` | Route files for any CRUD-shaped resource (top-level and sub-resource) |
| **entity_spec** | `EntitySpec` — single declaration of a domain entity | Audit binding, private-field visibility, route opt-ins, state-axis shape, related-list subresources, templates, parent chain for owned subentities, write_authz, body adapters, list filters, redirects. `to_resource_spec()` bridges to the mount helpers. Phase 1 of #317. | Route files + logic-layer handlers for entities migrated to this pattern (today: `users`, `providers`, the three provider-owned credentials, `posts`, and `user_favorite`). Per-entity instances live in `specs/<entity>.py`. Phase 1 is now complete — every entity is load-bearing on its spec. |

## Directory structure

**Core utility files:**

- `base_router.py` - Router wrapper that applies common decorators and configurations
- `responses.py` - Standardized response formatting for JSON and HTML
- `decorators.py` - Error handling and logging decorators applied to all routes
- `exceptions.py` - `APIException` subclasses (`NotFoundError`, `ForbiddenError`, ...) raised by logic, plus the fastapi-users → HTTP translator
- `forms.py` - HTTP-adapter primitives for request bodies: `parse_form_to_payload(request)` (form → dict, lists for repeated keys), `validate_or_422(adapter, payload_dict)` (run a `TypeAdapter`, translate `ValidationError` to 422 with `[{"loc","msg","type"}]`), and the back-to-back wrappers `parse_and_validate_form` / `parse_and_validate_json` (form-encoded vs. JSON body — state-axis subresources use the JSON variant). Home for any HTTP-adapter primitive that two or more route modules would otherwise import from each other.
- `projections.py` - `project_view(obj, *, public_fields, actor, private_fields=(), private_field_predicate=None)` builds a dict of `public_fields` from `obj` and conditionally appends `private_fields` when `private_field_predicate(actor, obj)` is true. Used by handlers that gate fields per viewer (today: user detail, where `email` / `is_active` / `is_verified` are visible only to the user themselves or an admin). Defense in depth alongside template-level guards: omitting keys at projection time means a forgotten `{% if %}` cannot re-leak. `ResourceSpec.private_fields` / `private_field_predicate` store the same primitives as declarative metadata so future cross-layer readers (JSON endpoint, audit snapshot, OpenAPI doc) can read the rule without rediscovering it.
- `resource_routes.py` - Unified `ResourceSpec` + opt-in `mount_*` grammar (covers top-level *and* sub-resource CRUD via `parent=`). See [Unified resource grammar](#unified-resource-grammar) below.
- `entity_spec.py` - `EntitySpec` dataclass: single declaration of a domain entity's identity (CRUD audit via `AuditedResource`, non-CRUD audit via `EdgeAudit`, private-field visibility, route opt-ins, state-axis shape, related-list subresources, templates, owned-subentity `parent` chain, write_authz, body adapters, list filters, HX-Redirects, `discriminator` binding for polymorphic entities, `M2NRelation` for M:N edges). Per-entity instances live under `specs/<entity>.py` and are read by route files (via `to_resource_spec()` for the mount helpers) and logic-layer handlers (for audit and visibility primitives). See [`EntitySpec`](#entityspec) below. Phase 1 of #317 is complete — every entity is load-bearing on its spec.
- `specs/` - Per-entity `EntitySpec` instances. One file per entity (today: `user.py`, `provider.py`, `provider_licensure.py`, `provider_education.py`, `provider_certification.py`, `post.py`, `user_favorite.py`). The three provider-credential specs share a factory in `_credential.py` since their `EntitySpec` shape is identical except for identity (name/model/id_param), audit-action enums, and schemas.

**Package infrastructure:**

- `__init__.py` - Exports all common utilities for easy import

## Unified resource grammar

`resource_routes.py` is the home for the unified `ResourceSpec` + opt-in `mount_*` grammar that covers every CRUD-shaped route. Every mount helper (`mount_list`, `mount_detail`, `mount_create`, `mount_update`, `mount_delete`, `mount_form`, `mount_state_axis`, `mount_related_list`) is landed and in use. After the EntitySpec rollout (#317 phase 1 + #326–#332 phase 2), migrated route files compose them through the higher-level `mount_entity` dispatcher rather than calling each helper individually — see [`mount_entity`](#mount_entity-dispatcher) below.

### The shape

A resource declares its identity once as an `EntitySpec` in `src/api/common/specs/<entity>.py` (carries collection name, id param, primary repo, audit binding, auth deps, schemas, templates, redirect targets, route opt-ins, state axes, subresources, filters, discriminator binding, M:N relation). The route file derives a `ResourceSpec` from the entity spec via `.to_resource_spec()` and passes a handlers dict to `mount_entity`, which reads the spec's `routes` flags + `state_axes` + `subresources` and calls the right underlying `mount_*` helper for each:

```python
from src.api.common.resource_routes import mount_entity
from src.api.common.specs.user import USER_ENTITY
from src.logic._generic import make_delete_handler
from src.logic.providers.provider_processing import handle_list_user_providers
from src.logic.users.user_processing import (
    handle_delete_user,                # bespoke (self-guard)
    handle_get_user_detail,
    handle_list_users,
    handle_set_user_activation,
)

users_api_router = APIRouter(prefix="/users")
router = BaseRouter(router=users_api_router, default_tags=["users"])

mount_entity(
    router,
    USER_ENTITY,
    handlers={
        "list": handle_list_users,
        "detail": handle_get_user_detail,
        "delete": handle_delete_user,                 # bespoke handler
        "providers": handle_list_user_providers,      # related-list subresource
        "activation": handle_set_user_activation,     # state-axis verb
    },
)
```

The underlying `mount_*` helpers stay available for entities whose URL shape doesn't fit `mount_entity`'s dispatch — favorites' M:N edge add/remove is the current example; its route file hand-rolls POST/DELETE without `mount_entity` because no edge mount helper exists.

### Why this shape

- **Opt-in mounts.** A read-only resource simply doesn't call `mount_create`/`mount_update`/`mount_delete` — there's no `read_only=True` flag because *not calling the mount* is the cleanest way to express "don't expose this verb." A backend-only resource (e.g. an async verification record written by a worker) still declares `audit_resource` so the worker can call `mutate(...)`, but the route file mounts only `mount_list` / `mount_detail`.
- **Spec is identity, mounts are operations.** Adding a new mount function (`mount_list`, `mount_create`, ...) doesn't change `ResourceSpec`'s shape for resources that don't use it — defaults are `None`. The dataclass grows fields incrementally as new mounts land.
- **Sub-resources nest via `parent`.** A child `ResourceSpec` carrying `parent=parent_spec` produces paths like `/providers/{provider_id}/licensures/{licensure_id}` — same `mount_create`/`mount_update`/`mount_delete` functions as top-level resources. The router's prefix is the topmost ancestor's collection (e.g. `APIRouter(prefix="/providers")`); the mount walks the parent chain to build the rest of the path. Handler kwargs include every parent id by its declared `id_param` name (`provider_id=...`, then the resource's own id).
- **Polymorphic resources via handler-driven knobs.** Posts dispatch templates by `kind`; the route doesn't need to. The handler returns a `template_name` in its context dict and the mount honors it. This keeps the spec's shape stable even when the resource's behavior is polymorphic — `mount_form` for `GET /posts/{id}/form` uses this in slice 7. The grammar isn't infinitely flexible though: `GET /posts/form?kind=X` (where the *query param* picks the template) stays bespoke because mount_form's contract doesn't carry query params, and widening it for one case would bloat every spec.

### Handler signatures drive dep wiring

The mount layer reads each handler's **typed signature** and synthesizes a FastAPI route function that pairs every parameter with the right source. There is no per-mount `extra_repo_deps` / `audit_repo_dep` wiring — the handler's annotations are the contract.

Synthesis recognizes:

- **`<id_param>: UUID`** (and any parent ids for sub-resources) — bound from the URL path.
- **`repo: <RepoType>`** — `Depends(spec.repo_dep)`. The annotation is informational; the spec is the source of truth for which resolver to call.
- **`audit_repo: AuditRepository`** and any other **`<name>: <RepoType>`** — resolved via the type→resolver registry in [`src/repositories/dependencies.py`](../../repositories/dependencies.py). Adding a new repo type means adding one entry to `_REPO_TYPE_RESOLVERS`.
- **`requesting_user: User`** — `Depends(spec.read_user_dep)` on reads, `Depends(spec.write_user_dep)` on writes. Declare as **`User | None`** for routes that may run anonymously (e.g. `mount_list(..., public=True)`).
- **`payload: <PydanticType>`** — parsed from the request body via the spec's `create_adapter` / `update_adapter` (or the mount's `body_schema` for `mount_state_axis`).
- **Query params** — declared in the mount's `query_params=` tuple; the handler param's name must match `QueryParam.name`.

Forgetting to register a new repo type in `_REPO_TYPE_RESOLVERS` raises `MountError` at app startup with a message naming the unresolved type — the failure mode is loud and immediate.

### What's mounted today

| Mount helper | Used by (post-`mount_entity`) |
| --- | --- |
| `mount_list` / `mount_detail` | every migrated entity (users, providers, posts) |
| `mount_create` / `mount_update` | providers, posts, the three provider-owned credential subentities |
| `mount_delete` | users (bespoke handler), providers, posts, credential subentities (factory-built handlers) |
| `mount_form` | providers (new + edit), posts (new + edit; posts derive the `?kind=` Literal from `entity.discriminator.names`) |
| `mount_related_list` | users (GET `/{id}/providers`) |
| `mount_state_axis` | users (PUT `/{id}/activation`) |
| Sub-resource via `parent=` on the spec | credential subentities (mounted via `mount_entity(..., owned_subentities=(...))`) |
| Hand-rolled (no mount helper fits) | favorites' POST/DELETE on `/users/me/favorites/{provider_id}` — M:N edge add/remove |

### Multi-repo handlers

Some handlers need more than the resource's primary repo — e.g. `handle_get_user_detail` takes both the user repo (the primary) and the provider repo (to embed the owned-providers list on the user-detail page). Just declare each as a typed parameter:

```python
async def handle_get_user_detail(
    request: Request,
    user_id: UUID,
    repo: UserRepository,
    provider_repo: ProviderRepository,
    requesting_user: User,
) -> dict: ...

mount_detail(router, USER_SPEC, handler=handle_get_user_detail)
```

The mount introspects the signature and resolves `provider_repo` via the type registry — no `extra_repo_deps=` wiring on the call. Adding a new repo to an existing handler is a one-line change in the handler's signature; the mount picks it up automatically.

### Query-param mounts

`mount_list` and `mount_form` accept a per-mount `query_params=` kwarg — a tuple of `QueryParam(name, annotation, default)` declarations. Each becomes a FastAPI `Query(...)` parameter on the route signature (so OpenAPI docs and 422-on-invalid validation work like a hand-written route would), and the parsed value reaches the handler under its declared name.

```python
# Filtered list — providers' license_type / issuing_state filters.
mount_list(
    router, PROVIDER_SPEC, handler=handle_list_providers,
    public=True,                                          # see below
    query_params=(
        QueryParam("license_type", str | None, None),
        QueryParam("issuing_state", str | None, None),
    ),
)

# Polymorphic-by-query form — posts' ?kind=client_referral picks the template.
mount_form(
    router, POST_SPEC, handler=handle_get_post_form,
    query_params=(QueryParam("kind", Literal[*POST_KIND_NAMES], POST_KIND_NAMES[0]),),
)
```

For the kind-picks-template case, the handler returns `template_name=...` in its context dict and the existing three-source resolution (handler-context > kwarg > spec) renders it.

`mount_list` also accepts `public=True` to override the spec's `read_user_dep` for that mount only — used when a resource's list is public but its detail/form pages are authenticated (providers). The handler still receives `requesting_user=None` for kwarg uniformity.

### Singleton aliases (e.g. `/users/me`)

`mount_detail` and `mount_related_list` accept a per-mount `singleton_alias=("me", session_dep)` kwarg. When set, the mount registers an additional route at `/<collection>/<alias>[...]` whose resource id is sourced from `session_dep().id` instead of the URL. Same handler, same template — the alias is purely an id-derivation convenience.

```python
mount_detail(
    router, USER_SPEC, handler=handle_get_user_detail,
    singleton_alias=("me", current_active_user),
)
# Mounts BOTH GET /users/{user_id} AND GET /users/me; same handler with
# user_id=<URL> or <session.id>.

mount_related_list(
    router, parent_spec=USER_SPEC, child_spec=PROVIDER_SPEC,
    handler=handle_list_user_providers,
    template="users/providers_list.html",
    singleton_alias=("me", current_active_user),
)
# Mounts /users/{user_id}/providers AND /users/me/providers.
```

The mount registers the alias path BEFORE the parametric one within the same router so FastAPI matches `/users/me` against the literal alias instead of trying to parse `me` as a UUID against `/users/{user_id}`.

### `mount_entity` dispatcher

Migrated route files compose the individual `mount_*` helpers through `mount_entity(router, entity, *, handlers, owned_subentities=(), detail_extras=None, detail_extra_repos=())`. The dispatcher reads:

- `entity.routes` (the `RouteSet` opt-in flags) — fires `mount_list` / `mount_detail` / `mount_create` / `mount_update` / `mount_delete` / `mount_form` (new and edit) for each `True` flag.
- `entity.state_axes` — one `mount_state_axis` call per axis, threading `axis.body_schema`, `axis.action`, `axis.response_to_dict` from the spec.
- `entity.subresources` — one `mount_related_list` call per `RelatedListSubresource` declaration.
- `entity.filters` — passed as `query_params=` to `mount_list`.
- `entity.discriminator` — if set, the form-new mount auto-derives `Literal[*entity.discriminator.names]` for the `?kind=` query param.
- `entity.read_user_dep` — `None` means public read; `mount_list` is called with `public=True`.
- `owned_subentities` — a tuple of child `EntitySpec`s whose `parent` is `entity`. Each is mounted recursively via the same dispatcher; the handlers dict for an owned subentity is keyed `f"{owned.name}.{verb}"` (e.g. `"licensure.create"`). For verbs that match the standard CRUD-framework factories (`create`, `update`, `delete`, `detail`, `form_edit`), the explicit key is optional — `mount_entity` falls back to `make_<verb>_handler(owned)`, which is the common case for subentities whose mutations are entirely standard. Verbs without a default factory (`list`, `form_new`) still require an explicit entry; supplying any explicit key overrides the factory default.

**Top-level CRUD verbs follow the same auto-bind path as owned subentities.** When a top-level entity opts into `detail` / `create` / `update` / `delete` / `form_edit` and the matching key is *absent* from `handlers`, `mount_entity` builds the handler from `make_<verb>_handler(entity)` and stitches it onto the route file's module as `_handle_<verb>_<entity>` (e.g. `_handle_update_provider`). That's the path contract-test monkey-patches at `src.api.routes.<entity>._handle_<verb>_<entity>` resolve through; setting `__module__` on the built handler lets the mount layer's `_resolve_handler` find the patched version via `getattr(sys.modules[__module__], __name__)`. The target module is auto-detected from the `mount_entity` caller's frame, so route files don't pass `module=`. Bespoke verbs (e.g. `handle_delete_user`'s self-guard, `handle_create_provider`'s inline credentials append) stay explicit in the handlers dict and override the factory default.

`detail_extras=` and `detail_extra_repos=` flow through to `make_detail_handler` when auto-binding the detail handler. They live on the `mount_entity` call site (route file) rather than on the spec because `provider_detail_extras` / `user_detail_extras` themselves import their `<ENTITY>_ENTITY` — placing them on the spec would close the cycle. Validators raise at mount time if `detail_extras` is set without `routes.detail=True`, alongside an explicit `handlers["detail"]`, or `detail_extra_repos` without a `detail_extras` consumer.

The handlers dict is validated at mount time: every opted-in flag / state axis / subresource must have a matching key (explicit or auto-bound for standard CRUD verbs), and any extra keys raise (typo detection). Missing entries fail loudly at app startup.

`mount_entity` is dispatch glue — it doesn't change behavior, it just composes the existing mount helpers from one declaration. The individual `mount_*` functions stay the right tool for entities whose URL shape doesn't fit the standard set (favorites' edge POST/DELETE).

### Generic CRUD handler factories

For the standard CRUD verbs (create / update / delete) plus the detail and edit-form reads, the `src/logic/_generic.py` module provides:

- `handle_create(spec, *, payload, repo, audit_repo, requesting_user, parent_id=None)` — load (subentity case) / instantiate (standard case) / dispatch on `spec.discriminator` for polymorphic entities; persist; audit via `mutate(verb="create")`.
- `handle_update(spec, *, target_id, payload, repo, audit_repo, requesting_user, parent_id=None)` — load → write_authz → polymorphic kind-invariant check → patch via `mutate(verb="update")`.
- `handle_delete(spec, *, target_id, repo, audit_repo, requesting_user, parent_id=None)` — load → write_authz → audited delete via `mutate(verb="delete")`.
- `handle_detail(spec, *, request, target_id, repo, requesting_user, extras=None, extra_kwargs=None)` — load → optional `can_edit` from `spec.can_write` → optional entity-specific extras callable for per-viewer / per-pair / related-collection state. The extras callable receives `target`, `request`, `requesting_user`, plus any `extra_kwargs`; its return dict merges into the context (last-write-wins, so extras can override the base `spec.name` binding — e.g. users binds under `target_user` for the projected view).
- `handle_get_edit_form(spec, *, request, target_id, repo, requesting_user)` — load → write_authz → context dict binding the entity under `spec.name`. For polymorphic entities, populates `template_name` from `spec.discriminator[kind].edit_template` so `mount_form`'s template-precedence renders the per-kind edit page.

And matching `make_<verb>_handler(spec)` factory functions (`make_create_handler`, `make_update_handler`, `make_delete_handler`, `make_detail_handler`, `make_edit_form_handler`) that build callables with synthesized signatures so `mount_*` introspection (per #316) wires the right deps. `make_detail_handler` additionally accepts `extras=` (the pure-function hook) and `extra_repos=` (typed-repo params the synthesis adds to the signature so the registry resolves them). Route files don't call the factories directly today — `mount_entity` invokes them under the hood for any standard-CRUD verb the entity opts into without supplying an explicit handler (see [`mount_entity`](#mount_entity-dispatcher)). The built handlers are stitched onto the route module as `_handle_<verb>_<spec.name>` so contract tests can patch via the same path that worked before auto-binding landed:

```python
# in src/api/routes/providers.py
from src.logic.providers.provider_processing import (
    handle_create_provider,           # bespoke (inline credentials append)
    handle_get_provider_form,
    handle_list_providers,
    provider_detail_extras,
)
from src.repositories.favorites.user_favorite_repository import UserFavoriteRepository

# update / delete / form_edit auto-bound to make_<verb>_handler(PROVIDER_ENTITY)
# via `mount_entity`; bespoke entries stay explicit in handlers.
mount_entity(
    router,
    PROVIDER_ENTITY,
    handlers={
        "list": handle_list_providers,
        "create": handle_create_provider,           # bespoke (inline credentials append)
        "form_new": handle_get_provider_form,
    },
    detail_extras=provider_detail_extras,           # supplies `is_favorited` per (viewer, provider) pair
    detail_extra_repos=(("user_favorite_repo", UserFavoriteRepository),),
    owned_subentities=(LICENSURE_ENTITY, EDUCATION_ENTITY, CERTIFICATION_ENTITY),
)
```

**When to use factory vs. bespoke handler.** Use the factory when the verb does the standard load → auth → mutate → audit ritual. Write a bespoke handler when the entity has rules that don't fit:

- `handle_delete_user` is bespoke because of the self-guard (admin can't delete self).
- `handle_create_provider` is bespoke because it appends initial credential sub-rows from the inline payload after the parent persists.
- `handle_add_favorite` / `handle_remove_favorite` are bespoke because they're M:N edge mutations, not CRUD.

Bespoke handlers still use `mutate(...)` for audit + commit; they just own the orchestration their entity needs.

The framework code itself lives in `src/logic/_generic.py` — see [`src/logic/README.md`](../../logic/README.md) for its place in the logic layer's shared tier alongside `_authz.py` and `audit.py`. The public framework-facing methods on `BaseRepository` (`get_by_model_id`, `create`, `delete`, `patch`, `add_child`, `create_polymorphic`) are documented in [`src/repositories/README.md`](../../repositories/README.md).

### Per-mount references

Per-mount docstrings in `resource_routes.py` are the canonical reference for required spec fields and exact handler kwargs.

## `EntitySpec`

`entity_spec.py` defines `EntitySpec`, the **upstream declaration** of a domain entity. Where `ResourceSpec` (above) is what the mount helpers consume, `EntitySpec` is the single declaration the rest of the codebase reads from. Phase 1 of #317 is complete — every entity in the codebase (`users`, `providers` + its three credential subentities, `posts`, `user_favorite`) is load-bearing on its spec.

### What it captures

Per-entity instances at `src/api/common/specs/<entity>.py` carry:

- **Identity** — `name`, `url_collection`, `id_param`, `model`, `owner_attr`.
- **Ownership chain** — `parent: EntitySpec | None` for owned subentities (the three provider credential entities set `parent=PROVIDER_ENTITY`).
- **FastAPI deps** — `repo_dep`, `read_user_dep`, `write_user_dep`. `read_user_dep=None` declares a public read.
- **Write authorization** — prefer `auth_policy=<AuthzPolicy>` over the hand-wired `write_authz` + `can_write` pair. `AuthzPolicy` carries the raising form (consumed by mutation handlers) and the predicate sibling (bound to detail-handler `can_edit` flags) as one declaration; the constructor expands the policy to populate both fields. The canonical sentinel `OWNER_OR_ADMIN` (defined in `entity_spec.py` alongside `AuthzPolicy`) pairs `assert_owner_or_admin` + `is_owner_or_admin` — used by provider, post, and the three credentials. The hand-wired form (`write_authz=` and/or `can_write=` directly) stays accepted for one-off rules but is mutually exclusive with `auth_policy`.
- **Audit binding** — exactly one of: `audit_snapshot: type[BaseModel] | Callable` (+ optional `audit_action_stem`) for CRUD-shaped entities — the constructor calls `make_audited_resource(name, snapshot, action_stem=stem)` and stores the result on `audit`; or `edge_audit: EdgeAudit` for non-CRUD edges (favorites uses `edge_audit` with the `(add, remove)` verb map). Hand-built `audit=<AuditedResource>` is still accepted but mutually exclusive with `audit_snapshot`; specs should prefer the declarative form. Construction-time validation enforces all three exclusivity rules.
- **Visibility** — `private_fields`, `private_field_predicate` (the projection rule from #304).
- **Route opt-ins** — `routes: RouteSet` flags: `list`, `detail`, `create`, `update`, `delete`, `form_new`, `form_edit`. Phase 1 reads these for documentation + spec-correctness tests; `mount_entity` (added in phase 2) consumes them at mount time.
- **State axes** — `state_axes: tuple[StateAxis, ...]` (axis name, body schema, audit action, response projection).
- **Related-list subresources** — `subresources: tuple[RelatedListSubresource, ...]` (child spec, template, optional `singleton_alias`).
- **Templates** — `templates: Templates` for the list/detail/form_new/form_edit views. Each field defaults by convention to `f"{url_collection}/{verb}.html"` for any verb the entity opts into via `RouteSet`. Specs only declare a path when it diverges from the convention (no current entity does).
- **Body adapters + redirects** — `create_adapter`, `update_adapter`, `create_redirect`, `update_redirect`, `delete_redirect`. The two redirect shapes the codebase uses live on the `Redirects` namespace: `Redirects.to_edit_form(collection, id_param)` builds the callable returning `/<collection>/{id}/form`; `Redirects.to_detail(collection, id_param)` returns `/<collection>/{id}`. Specs declare these instead of repeating one-liner lambdas. `create_adapter` / `update_adapter` accept either a Pydantic class or a pre-built `TypeAdapter`; the constructor wraps a plain class once so the downstream mounts always see an adapter. Discriminated-union schemas (posts) pass the pre-built adapter. For the PATCH/PUT response projection, prefer `read_schema=<BaseModel | TypeAdapter>` — the constructor synthesizes `read_to_dict` from it (`schema.model_validate(obj).model_dump(mode="json")` for a plain class, `adapter.validate_python(obj).model_dump(mode="json")` for a `TypeAdapter` covering a discriminated union). The hand-built `read_to_dict=` form stays accepted but is mutually exclusive with `read_schema`.
- **List filters** — `filters: tuple[QueryParam, ...]` (providers declares `license_type` + `issuing_state`; the route layer threads them to `mount_list`).
- **Polymorphism** — `discriminator: DiscriminatorRegistry[Any] | None`. Posts sets this to `POST_KINDS`; phase-2 generic `handle_create` / `handle_update` dispatches via the registry to find the per-kind detail model.
- **M:N relationships** — `relation: M2NRelation | None`. Favorites declares the User → Provider join via `user_favorites`.

### How layers read from it

```python
# Route file: a single mount_entity call consumes the spec.
mount_entity(
    router,
    USER_ENTITY,
    handlers={
        "list": handle_list_users,
        "detail": handle_get_user_detail,
        "delete": handle_delete_user,
        "providers": handle_list_user_providers,
        "activation": handle_set_user_activation,
    },
)

# Logic-layer handler: read audit + visibility primitives.
async with mutate(repo, audit_repo, ..., resource=USER_ENTITY.audit, verb="delete"):
    await repo.delete(target)

view = project_view(
    target,
    public_fields=("id", "username"),
    actor=requesting_user,
    private_fields=USER_ENTITY.private_fields,
    private_field_predicate=USER_ENTITY.private_field_predicate,
)

# Polymorphic dispatch (posts): the discriminator is on the spec.
spec = POST_ENTITY.discriminator[payload.kind]
detail = spec.detail_model(...)
```

### Spec is metadata-only; handlers stay at the call site

`StateAxis.handler` and `RelatedListSubresource.handler` exist as fields but stay `None` by convention. Including a handler reference would mean `api.common.specs.<entity>` importing from `src.logic.<entity>`, which is the opposite of the usual layer direction and creates a circular import with handlers that themselves read from the spec. Route files supply the handler in the `mount_entity` handlers dict (or, equivalently, in the matching individual `mount_*` call for the rare entity that doesn't use `mount_entity`).

This is a deliberate design call, not a phase-1 deferral. The framework-generic CRUD handlers (`handle_create` / `handle_update` / `handle_delete`) read the spec at call time, not at module-import time; they sidestep the cycle.

### Cross-entity references

`M2NRelation.from_entity` and `to_entity` are `EntitySpec` instances; favorites references `USER_ENTITY` + `PROVIDER_ENTITY` directly. `RelatedListSubresource.child_spec` is a `ResourceSpec` (the bridge type the mount helpers consume); the users spec calls `PROVIDER_ENTITY.to_resource_spec()` to produce one.

### What's *not* meant for this grammar

The grammar fits resource-shaped routes. It's deliberately **not** a home for:

- **Auth flows** — register/login/verify/reset-password live in `auth_routes.py` / `auth_pages.py`. State-machine semantics, not CRUD.
- **Utility endpoints** — `/`, `/health`.

Slice 10 (#255) documents these explicitly. If a future case suggests the grammar should grow to fit them, that's the moment to reshape `ResourceSpec`, not to escape-hatch around it.

## Implementation patterns

### Baserouter pattern for standardized routes

All route files use BaseRouter to get consistent behavior:

```python
# In any route file
from fastapi import APIRouter
from src.api.common import BaseRouter

# Create underlying apirouter
users_router_instance = APIRouter()

# Wrap with baserouter for standardized features
router = BaseRouter(
    router=users_router_instance,
    default_tags=["users"],
    default_dependencies=[Depends(some_common_dep)]
)

# Routes automatically GET:
# - error handling decorator
# - logging decorator
# - default tags and dependencies
@router.get("/users")
async def list_users():
    # Just implement the logic - error handling is automatic
    return await handle_list_users()
```

### Response helpers for consistent formatting

Use `APIResponse.html_response` for HTML pages and the module-level `*_response` helpers for HTMX-driven mutations:

```python
from src.api.common import (
    APIResponse,
    created_response,
    deleted_response,
    refreshed_response,
    updated_response,
)

# HTML template responses
@router.get("/users")
async def list_users_page(request: Request):
    users = await get_users()
    return APIResponse.html_response(
        template_name="users/list.html",
        context={"users": users},
        request=request,
    )

# Mutation responses (HTMX-aware)
return created_response(id=user.id, location=f"/users/{user.id}")
return updated_response(hx_redirect=f"/users/{user.id}")
return deleted_response(hx_redirect="/users")
return refreshed_response()

# Error responses are *raised*, not returned — logic handlers raise an
# APIException subclass and the @handle_route_errors decorator turns it
# into the right HTTP status. See "Error handling pattern" below.
```

### Error handling pattern

Logic-layer `handle_*` functions raise the API exception classes directly. They're `HTTPException` subclasses, so the `@handle_route_errors` decorator passes them through to FastAPI unchanged. There is **no separate domain-error hierarchy** — see [Error handling](../../README.md#error-handling) in the parent `src/README.md`.

```python
# logic/post_processing.py
from src.api.common.exceptions import ForbiddenError, NotFoundError

async def handle_update_post(post_id, payload, post_repo, requesting_user):
    post = await post_repo.get_post_with_detail(post_id)
    if post is None:
        raise NotFoundError(detail="Post not found")          # → 404
    if post.owner_id != requesting_user.id and not requesting_user.is_admin:
        raise ForbiddenError(detail="Only the owner or an admin can edit this post")  # → 403
    ...
    await post_repo.session.commit()
    return post

# api/routes/posts.py
@router.put("/posts/{post_id}")
async def update_post(post_id: UUID, payload: PostUpdate, ...):
    return await handle_update_post(post_id, payload, post_repo, current_user)
```

The decorator's only active translation is for `fastapi_users_exceptions.FastAPIUsersException` (registration/auth flow): `UserAlreadyExists` → 400 with the standard error code, `InvalidPasswordException` → 400 with the reason. Anything else that escapes a handler becomes a generic 500.

### Logging pattern

All routes get automatic structured logging:

```python
# Automatic logging via decorator (no manual code needed)
@router.get("/users")
async def list_users():
    # Entry log: "Entering route: list_users (args: [...], kwargs: [...])"
    result = await handle_list_users()
    # Success log: "Successfully exited route: list_users"
    return result
    # Error log (if exception): "Error during route: list_users. Exception: ..."
```

## Common issues and solutions

### Issue: Inconsistent error responses

**Problem**: Different routes return errors in different formats
**Solution**: Always use BaseRouter and let decorators handle errors

```python
# Bad - manual error handling
@router.get("/users")
async def list_users(user_repo: UserRepository = Depends(get_user_repository)):
    try:
        return await handle_list_users(user_repo)
    except NotFoundError as e:
        return {"error": str(e)}  # Inconsistent format, swallows the HTTPException

# Good - let the HTTPException propagate
router = BaseRouter(router=APIRouter())

@router.get("/users")
async def list_users(user_repo: UserRepository = Depends(get_user_repository)):
    return await handle_list_users(user_repo)
    # NotFoundError raised inside handle_list_users → 404 via FastAPI
```

### Issue: Missing logging for debugging

**Problem**: Hard to debug route issues without consistent logging
**Solution**: BaseRouter applies logging automatically

```python
# Bad - manual logging
@router.get("/users")
async def list_users(user_repo: UserRepository = Depends(get_user_repository)):
    logger.info("Listing users")
    try:
        result = await handle_list_users(user_repo)
        logger.info("Users listed successfully")
        return result
    except Exception as e:
        logger.error(f"Failed to list users: {e}")
        raise

# Good - automatic logging
router = BaseRouter(router=APIRouter())

@router.get("/users")  # Logging automatic
async def list_users(user_repo: UserRepository = Depends(get_user_repository)):
    return await handle_list_users(user_repo)
```

### Issue: Mixed response formats

**Problem**: Some routes return raw data, others use response objects
**Solution**: Always use APIResponse for consistency

```python
# Bad - bespoke response shape per route
@router.post("/users")
async def create_user(...):
    user = await handle_create_user(...)
    return {"id": str(user.id), "status": "ok"}  # Custom format

# Good - shared mutation helper
@router.post("/users")
async def create_user(...):
    user = await handle_create_user(...)
    return created_response(id=user.id, location=f"/users/{user.id}")
```

## Available decorators and utilities

### Decorators (applied automatically by baserouter)

Both decorators are wrapped onto every endpoint by `BaseRouter`; route files don't import them directly. Logging covers entry/exit/error; error handling passes `HTTPException` through, translates fastapi-users exceptions, and converts anything unexpected into a 500. `handle_route_errors` is exported from `src.api.common` for tests that want to invoke it directly.

### Response utilities

```python
# Mutation helpers (module-level functions in responses.py)
created_response(id, location, hx_redirect=None)   # 201, sets Location + HX-Redirect
updated_response(body=None, hx_redirect=...)       # 200 + HX-Redirect
updated_response(body=..., hx_refresh=True)        # 200 + HX-Refresh (state-axis flips)
deleted_response(hx_redirect=...)                  # 204 + HX-Redirect
refreshed_response()                               # 200 + HX-Refresh: true (no body)

# HTML responses (method on APIResponse)
APIResponse.html_response(template_name, context, request, current_user=None)
```

`html_response` merges three context tiers (later overwrites earlier): caller `context` → dev/global context → chrome scalars from `base_context(current_user)` (`is_authenticated`, `is_admin`, `current_username`, `current_user_id`). Chrome scalars are computed from the authenticated user and overwrite caller-provided values — a handler can't accidentally pass `is_admin=True` for a non-admin viewer. Mount functions in `resource_routes.py` thread `requesting_user` to `current_user`; auth-page handlers (no auth dep) take the default `None`.

### Exception classes

```python
# APIException subclasses exported from src.api.common, raised directly by logic handlers
NotFoundError(detail)       # 404
BadRequestError(detail)     # 400
ForbiddenError(detail)      # 403

# fastapi-users exception translator (called by the decorator)
handle_fastapi_users_error(fastapi_users_exception) -> APIException
```

`exceptions.py` also defines `UnauthorizedError` (401) and `InternalServerError` (500), but they're not currently used by any handler and are not re-exported from `__init__.py`. Import them from `src.api.common.exceptions` directly if a future handler needs them.

## Tests

Colocated tests cover the helpers in this directory:

- `test_responses.py` — `APIResponse`, `created_response`, `updated_response`, `deleted_response`, `refreshed_response`.
- `test_resource_routes.py` — `ResourceSpec` + per-mount tests (covers sub-resource routes via `parent=` since slice 8 / #253). Add a test here whenever a new mount function lands or an existing one grows a knob.
- `test_projections.py` — `project_view` (per-viewer field gating).
- `test_middleware.py` — ASGI middleware (currently just `StripEmptyQueryParamsMiddleware`'s pair-stripping helper; integration coverage lives next to the routes it affects).

Route-level tests under `../routes/` exercise the mounts indirectly via the resources that use them; the unit tests here cover spec validation, error handling at mount time, and the path-param wiring that the route-level tests can't easily isolate.

## Related documentation

- [Routes Layer](../routes/README.md) - Route organization and patterns using common utilities
- [Logic Layer](../../logic/README.md) - Where the API exceptions in this package get raised
- [API Layer](../README.md) - Overall API layer architecture
