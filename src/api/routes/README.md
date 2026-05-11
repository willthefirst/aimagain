# API routes: Domain-organized HTTP endpoints

The `api/routes/` directory contains **domain-specific route handlers** that define HTTP endpoints for the application, organized by business domain with consistent patterns for request handling, delegation to business logic, and response formatting.

> **Resource design contract — read first.** URL shape, lifecycle states, subresource conventions, and the rules for when to introduce one are defined in [`RESOURCE_GRAMMAR.md`](RESOURCE_GRAMMAR.md). Every resource in this codebase MUST conform to that grammar. This README describes *how routes are organized and wired*; the grammar describes *what URLs and lifecycles a resource MUST present*.

## Core philosophy: Thin routes with domain organization

Routes are **ultra-thin HTTP adapters** that handle request parsing, delegate to processing logic, and format responses while being organized by business domains for maintainability.

CRUD-shaped routes use the **`EntitySpec` declaration + `mount_entity` dispatcher**. Each entity declares its identity once in [`src/api/common/specs/<entity>.py`](../common/README.md#entityspec) (carries `routes` opt-in flags, audit binding, state axes, subresources, filters, discriminator, templates, etc.) and the route file calls `mount_entity(router, ENTITY, handlers={...})`. The dispatcher reads the spec and fires the right underlying `mount_*` helper for each opted-in verb. Sub-resources nest via the child entity's `parent=PARENT_ENTITY` field and are passed through `owned_subentities=` on the dispatcher. Routes that don't fit the grammar (auth flows, `/me/*` singletons, M:N edge add/remove, utility endpoints) stay hand-written — see [Bespoke routes](#bespoke-routes) below.

The underlying `mount_*` helpers (`mount_list`, `mount_detail`, `mount_create`, `mount_update`, `mount_delete`, `mount_form`, `mount_state_axis`, `mount_related_list`) remain available for entities whose URL shape `mount_entity` can't handle — favorites' M:N edge POST/DELETE is the only current example. Every other entity (users, providers + 3 credential subentities, posts) composes through `mount_entity`.

For the standard CRUD verbs (create / update / delete), the route file binds handlers built by `make_<verb>_handler(ENTITY)` from [`src/logic/_generic.py`](../../logic/README.md). Bespoke handlers are written only when the entity has rules that don't fit the standard load → auth → mutate → audit ritual (current examples: users' delete self-guard, providers' create with nested credential append, favorites' edge ops).

### What we do

- **Domain organization**: one route file per resource, named after the resource.
- **Thin route handlers**: Routes only handle HTTP concerns; business logic stays in `logic/`.
- **`EntitySpec` + `mount_entity` for CRUD**: Declare the spec once in `api/common/specs/`, call `mount_entity(router, ENTITY, handlers={...})`. The route file becomes a manifest, not a hand-rolled CRUD wall.
- **Hand-written for the routes that don't fit**: Auth flows, singletons, M:N edge add/remove, utility endpoints stay explicit — the grammar is for resource-shaped routes, not protocols.
- **Consistent delegation**: All routes delegate to processing functions in `logic/`.
- **Standardized patterns**: BaseRouter wraps every route with error handling and logging.
- **Form-encoded mutations + HTMX response shape** are the route convention.

**Example**: a typical route file with the unified grammar (users):

```python
from src.api.common import make_entity_router
from src.api.common.resource_routes import mount_entity
from src.api.common.specs.user import USER_ENTITY
from src.logic.providers.provider_processing import handle_list_user_providers
from src.logic.users.user_processing import (
    handle_delete_user,             # bespoke (self-guard)
    handle_get_user_detail,
    handle_list_users,
    handle_set_user_activation,
)

router = make_entity_router(USER_ENTITY)
users_api_router = router.router  # re-exported for `main.py`

mount_entity(
    router,
    USER_ENTITY,
    handlers={
        "list": handle_list_users,
        "detail": handle_get_user_detail,
        "delete": handle_delete_user,
        "providers": handle_list_user_providers,        # related-list subresource
        "activation": handle_set_user_activation,       # state-axis verb
    },
)
```

The full grammar (knobs, dispatch rules, the underlying mount helpers, factory functions for generic CRUD handlers) is documented in [`api/common/README.md`](../common/README.md#unified-resource-grammar).

### What we don't do

- **Business logic in routes**: Complex validation, business rules, and processing stays in logic layer
- **Direct database access**: Routes never call repositories or database sessions directly
- **Mixed concerns**: HTTP handling separate from business logic and data access
- **Inconsistent error handling**: All routes use BaseRouter for standardized error responses

**Example**: Don't implement business logic in routes:

```python
# Bad - business logic in route
@router.post("/[entities]")
async def create_entity(data: dict, session: AsyncSession = Depends()):
    if not data.get("name"):
        raise HTTPException(400, "Name required")
    entity = await session.execute(select([Entity]).filter(...))

# Good - delegate to logic handler
@router.post("/[entities]")
async def create_entity(
    data: [Entity]Create,
    user: User = Depends(current_active_user),
    repo: [Entity]Repository = Depends(get_[entity]_repository),
):
    return await handle_create_entity(data, user, repo)
```

## Architecture: Domain-driven route organization

**HTTP Request -> Route Handler -> Logic Handler -> Repository -> Response**

Routes are organized by domain with consistent delegation patterns.

## Layer organization

- One route file per resource: `<resource>.py` defines the HTTP endpoints for that resource. Per-resource specifics — exact endpoints, mutation-response shapes, sub-resources, HX-Redirect behavior — live in that file's docstrings and (when worth writing down) in any cluster-level doc the resource owns.
- `auth_routes.py` and `auth_pages.py` are the JSON-API and HTML-page split for authentication; both follow the same delegation pattern as resource routes.
- `__init__.py` re-exports the route modules.

Singleton-alias routes like `/users/me` and `/users/me/providers` are mounted alongside their parametric counterparts via `singleton_alias=` on `mount_detail` / `mount_related_list` (see the [unified resource grammar](../common/README.md#singleton-aliases-eg-usersme)). They are not a separate route file.

The URL shape every resource MUST follow is defined in [`RESOURCE_GRAMMAR.md`](RESOURCE_GRAMMAR.md). This README documents how routes are wired; the grammar documents what URLs and lifecycles a resource MUST present.

## Bespoke routes

The unified grammar fits resource-shaped CRUD. Several existing routes intentionally stay hand-written. Each is a deliberate choice — adding a knob to `ResourceSpec` / `mount_entity` to fit them would bloat the grammar for one cluster's benefit.

| Route(s) | File | Reason it stays bespoke |
|---|---|---|
| `POST /auth/register` | `auth_routes.py` | Auth-flow protocol (token issuance, fastapi-users hooks). Not CRUD on a domain entity. |
| `GET /auth/{register,login,forgot-password,reset-password/{token}}` | `auth_pages.py` | Pure form rendering, no resource. Could fit a hypothetical `mount_static_form` but not worth it for 4 routes. |
| `GET /users/me`, `GET /users/me/providers` | `users.py` (mounted via `singleton_alias=`) | Singleton aliases — no parent id, session-sourced. Mounted as additional paths on the existing `mount_detail` / `mount_related_list` calls (which `mount_entity` invokes); see [`api/common/README.md`](../common/README.md#singleton-aliases-eg-usersme). |
| `POST /users/me/favorites/{provider_id}`, `DELETE /users/me/favorites/{provider_id}`, `GET /users/me/favorites` | `favorites.py` | M:N edge add/remove — the codebase has no `mount_*` helper for edge mutations, so the whole route file is hand-rolled. `FAVORITE_ENTITY` carries `edge_audit` + `relation: M2NRelation` to document the binding, but no `mount_entity` call applies. |
| `GET /`, `GET /health` | `main.py` | Utility endpoints. Not resource-shaped. |

If a future case suggests the grammar should grow to fit one of these (e.g. a second M:N entity arrives and edge mount helpers start to pay back), that's the moment to reshape — not to escape-hatch around it.

## Implementation patterns

### Adding a CRUD-shaped resource (the common case)

1. **Declare the spec** at `src/api/common/specs/<entity>.py`. The spec carries every per-entity declaration (identity, audit binding, route opt-ins, write_authz, body adapters, redirects, filters, templates, etc.). See existing examples in `specs/` — `user.py` (simplest), `provider.py` (with filters + form pages), `post.py` (with discriminator), `user_favorite.py` (edge / M:N).

2. **Add a spec-correctness test** at `src/api/common/specs/test_<entity>.py` asserting the spec declares the right values (audit type, owner_attr, route flags, etc.).

3. **Create the route file** `<resource>.py`. Call `mount_entity`; framework verbs auto-bind to `make_<verb>_handler(<ENTITY>_ENTITY)` and get stitched onto the route module as `_handle_<verb>_<entity>` (target module auto-detected from the caller frame) for contract-test patches. Only bespoke handlers (and `list` / `form_new`, which have no factory defaults) need explicit `handlers` entries.

```python
from src.api.common import make_entity_router
from src.api.common.resource_routes import mount_entity
from src.api.common.specs.<entity> import <ENTITY>_ENTITY
from src.logic.<entity>.<entity>_processing import (
    handle_list_<entity>,
    # ... plus any bespoke handlers that don't fit the generic ritual.
    # Per-viewer / per-list extras don't import here — they live on the
    # spec as `detail_extras_path` / `list_extras_path` and resolve at
    # mount time.
)

router = make_entity_router(<ENTITY>_ENTITY)
<entity>_api_router = router.router  # re-exported for `main.py`

mount_entity(
    router,
    <ENTITY>_ENTITY,
    handlers={
        "list": handle_list_<entity>,
        "form_new": handle_get_<entity>_form,
        # detail / create / update / delete / form_edit auto-bound from
        # make_<verb>_handler(<ENTITY>_ENTITY); add explicit entries here
        # only for verbs whose entity needs a bespoke handler.
    },
)
```

Auto-bound handlers expose the same `_handle_<verb>_<entity>` attribute on the route module that hand-written bindings used to — contract tests patching `src.api.routes.<entity>._handle_<verb>_<entity>` resolve through the mount layer's `_resolve_handler` either way.

4. Register the router in `src/main.py`. Order matters when literal segments would shadow parametric ones (e.g. `/me/*` aliases mount before parametric `/{id}` paths within the same router via `singleton_alias=` on the related subresource).

5. Add a colocated `test_<resource>.py`. Framework verbs are already covered by `src/logic/test__generic.py` + `src/api/common/test_resource_routes.py`; the route-level tests verify resource-specific behavior (bespoke handler logic, end-to-end happy paths, contract-test scenarios).

### Adding a sub-resource

Declare the child entity with `parent=PARENT_ENTITY` on its spec (see `specs/provider_licensure.py` etc.). Pass the child entity through `owned_subentities=` on the parent's `mount_entity` call; the dispatcher walks the chain to build paths like `/providers/{provider_id}/licensures/{licensure_id}`.

For each opted-in verb on the child, `mount_entity` looks for `handlers["<child.name>.<verb>"]`; if absent and the verb has a default CRUD factory (`create`, `update`, `delete`, `detail`, `form_edit`), it auto-binds `make_<verb>_handler(child)`. Common case — credentials' subrow CRUD is entirely standard:

```python
mount_entity(
    router,
    PROVIDER_ENTITY,
    handlers={
        # ... parent handlers ...
        # No `licensure.*` / `education.*` / `certification.*` entries needed:
        # mount_entity auto-binds make_create_handler / make_update_handler /
        # make_delete_handler for each opted-in verb on each owned subentity.
    },
    owned_subentities=(LICENSURE_ENTITY, EDUCATION_ENTITY, CERTIFICATION_ENTITY),
)
```

Supply `handlers["<child.name>.<verb>"]` only when the child needs a bespoke handler for that verb (e.g. a subentity create with side effects). Verbs without a default factory (`list`, `form_new`) always require an explicit entry — auto-binding would need bespoke knobs (custom repo query / template selection) that can't be inferred.

Each factory-built handler receives both `provider_id=` and the child id (e.g. `licensure_id=`), plus `payload=`, `repo=`, `audit_repo=`, `requesting_user=`.

### Baserouter pattern for consistency

All routes use BaseRouter for consistent behavior:

```python
from src.api.common import BaseRouter

# Wrap apirouter with baserouter for standardized features
router = BaseRouter(
    router=APIRouter(),
    default_tags=["domain"],
    default_dependencies=[Depends(some_common_dependency)]
)

# Routes automatically GET:
# - error handling decorators
# - logging decorators
# - common dependencies
# - consistent response formatting
```

### Response formatting patterns

Use APIResponse for consistent response handling:

```python
# HTML responses with templates
@router.get("/users")
async def list_users(request: Request):
    users = await handle_list_users()
    return APIResponse.html_response(
        template_name="users/list.html",
        context={"users": users},
        request=request,
    )

# JSON API responses
@router.get("/api/users")
async def list_users_api():
    users = await handle_list_users()
    return users  # Auto-serialized to JSON

# Redirect responses
@router.post("/[entities]")
async def create_entity_form():
    entity = await handle_create_entity()
    return RedirectResponse(
        url=f"/[entities]/{entity.id}",
        status_code=status.HTTP_303_SEE_OTHER
    )
```

## Common issues and solutions

### Issue: Business logic creeping into routes

**Problem**: Routes start containing validation, business rules, or data processing
**Solution**: Move all logic to processing layer, keep routes thin

```python
# Bad - business logic in route
@router.post("/[entities]")
async def create_entity(name: str = Form(...)):
    if len(name) < 3:  # Validation logic
        raise HTTPException(400, "Name too short")

# Good - delegate to processing
@router.post("/[entities]")
async def create_entity(name: str = Form(...)):
    return await handle_create_entity(name=name)
```

### Issue: Inconsistent error handling

**Problem**: Different routes handle errors differently
**Solution**: Use BaseRouter for standardized error handling

```python
# Bad - manual error handling in each route
@router.post("/[entities]")
async def create_entity():
    try:
        return await handle_create_entity()
    except ValueError as e:
        raise HTTPException(400, str(e))

# Good - BaseRouter handles errors automatically
router = BaseRouter(router=APIRouter())

@router.post("/[entities]")  # Error handling automatic
async def create_entity():
    return await handle_create_entity()
```

## Route registration

### Main application route registration

The order in which `app.include_router(...)` calls fire determines route precedence: any route adding a literal segment under another resource's parametric path must be registered first (or, if both come from the same router, mounted first inside it — `singleton_alias=` does this for `/users/me`).

The actual registration order lives in [`src/main.py`](../../main.py) — that's the source of truth, not this README.

### Route naming and organization

```python
# Consistent naming pattern
[domain]_router_instance = APIRouter()
router = BaseRouter(router=[domain]_router_instance)
```

The URL shape, HTTP method, and form-page conventions for every resource are defined in [`RESOURCE_GRAMMAR.md`](RESOURCE_GRAMMAR.md). Do not invent endpoint shapes here — follow the grammar.

## Tests

Tests are colocated with the routes they cover (`test_<resource>.py` next to `<resource>.py`). When adding a new route, add or extend the matching `test_*.py` file in this directory. Shared fixtures (`test_client`, `authenticated_client`, `db_test_session_manager`, `logged_in_user`) come from [`tests/fixtures.py`](../../../tests/fixtures.py); user-construction helpers from [`tests/helpers.py`](../../../tests/helpers.py).

Pact contract pairs for HTML forms and HX-driven buttons live under [`tests/test_contract/`](../../../tests/test_contract/README.md); per [`RESOURCE_GRAMMAR.md`](RESOURCE_GRAMMAR.md), every resource exposing an HTML form gets a contract pair.

## Related documentation

- [API Common](../common/README.md) - Shared API utilities and BaseRouter
- [Logic Layer](../../logic/README.md) - Processing logic that routes delegate to
- [API Layer](../README.md) - Overall API layer architecture
