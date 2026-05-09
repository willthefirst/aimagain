# API routes: Domain-organized HTTP endpoints

The `api/routes/` directory contains **domain-specific route handlers** that define HTTP endpoints for the application, organized by business domain with consistent patterns for request handling, delegation to business logic, and response formatting.

> **Resource design contract — read first.** URL shape, lifecycle states, subresource conventions, and the rules for when to introduce one are defined in [`RESOURCE_GRAMMAR.md`](RESOURCE_GRAMMAR.md). Every resource in this codebase MUST conform to that grammar. This README describes *how routes are organized and wired*; the grammar describes *what URLs and lifecycles a resource MUST present*.

## Core philosophy: Thin routes with domain organization

Routes are **ultra-thin HTTP adapters** that handle request parsing, delegate to processing logic, and format responses while being organized by business domains for maintainability.

CRUD-shaped routes use the **unified `ResourceSpec` + opt-in `mount_*` grammar** in [`src/api/common/resource_routes.py`](../common/README.md#unified-resource-grammar). A resource declares its identity once (`ResourceSpec`) and opts into the operations it wants exposed via `mount_list` / `mount_detail` / `mount_form` / `mount_create` / `mount_update` / `mount_delete` / `mount_related_list`. Sub-resources nest via `parent=`. Routes that don't fit the grammar (auth flows, `/me/*` singletons, idempotent state setters, query-param-driven polymorphism, utility endpoints) stay hand-written — see [Bespoke routes](#bespoke-routes) below.

### What we do

- **Domain organization**: one route file per resource, named after the resource.
- **Thin route handlers**: Routes only handle HTTP concerns; business logic stays in `logic/`.
- **`ResourceSpec` + `mount_*` for CRUD**: Declare a `ResourceSpec`, call the mount functions for the operations you want. The route file becomes a manifest, not a hand-rolled CRUD wall.
- **Hand-written for the routes that don't fit**: Auth flows, singletons, state-setters, etc. stay explicit — the grammar is for resource-shaped routes, not protocols.
- **Consistent delegation**: All routes delegate to processing functions in `logic/`.
- **Standardized patterns**: BaseRouter wraps every route with error handling and logging.
- **Form and JSON support**: Form-encoded mutations + HTMX response shape are the route convention.

**Example**: A typical route file with the unified grammar:

```python
USER_SPEC = ResourceSpec(
    collection="users",
    id_param="user_id",
    repo_dep=get_user_repository,
    audit_resource=USER,
    read_user_dep=current_active_user,
    write_user_dep=current_admin_user,
    list_template="users/list.html",
    detail_template="users/detail.html",
)

mount_list(router, USER_SPEC, handler=handle_list_users)
mount_detail(
    router, USER_SPEC, handler=handle_get_user_detail,
    extra_repo_deps=(get_provider_repository,),  # multi-repo handler
)
mount_delete(
    router, USER_SPEC, handler=handle_delete_user,
    audit_repo_dep=get_audit_repository,
)
```

The full grammar (knobs, mount kwargs, polymorphism via handler-context, sub-resources) is documented in [`api/common/README.md`](../common/README.md#unified-resource-grammar).

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
- `me.py` holds the `/users/me/*` aliases — current-user shortcuts whose handlers delegate to the same logic functions as the user-scoped routes, so behavior stays identical.
- `__init__.py` re-exports the route modules.

The URL shape every resource MUST follow is defined in [`RESOURCE_GRAMMAR.md`](RESOURCE_GRAMMAR.md). This README documents how routes are wired; the grammar documents what URLs and lifecycles a resource MUST present.

## Bespoke routes

The unified grammar fits resource-shaped CRUD. Several existing routes intentionally stay hand-written. Each is a deliberate choice — adding a knob to `ResourceSpec` to fit them would bloat the grammar for one cluster's benefit.

| Route(s) | File | Reason it stays bespoke |
|---|---|---|
| `POST /auth/register` | `auth_routes.py` | Auth-flow protocol (token issuance, fastapi-users hooks). Not CRUD on a domain entity. |
| `GET /auth/{register,login,forgot-password,reset-password/{token}}` | `auth_pages.py` | Pure form rendering, no resource. Could fit a hypothetical `mount_static_form` but not worth it for 4 routes. |
| `GET /users/me`, `GET /users/me/profile`, `GET /users/me/providers` | `me.py` | Singleton aliases — no parent id, session-sourced. Adding a `singleton_alias` knob to every spec for 3 routes would be a bad trade. |
| `PUT /users/{user_id}/activation` | `users.py` | Idempotent state set with `HX-Refresh` (not `HX-Redirect`); admin-only verb. Doesn't match `mount_update` semantics. |
| `GET /providers` (with `?license_type=`/`?issuing_state=` filters) | `providers.py` | Public listing with query-param filters. `mount_list` doesn't accept query params; widening it for one resource would push the asymmetry onto every spec. |
| `GET /posts/form?kind=X` | `posts.py` | Polymorphic-by-query-param: the kind picks the create template at request time. `mount_form`'s contract doesn't carry query params. |
| `GET /`, `GET /health` | `main.py` | Utility endpoints. Not resource-shaped. |

If a future case suggests the grammar should grow to fit one of these, that's the moment to reshape `ResourceSpec` — not to escape-hatch around it.

## Implementation patterns

### Adding a CRUD-shaped resource (the common case)

1. Create the route file `<resource>.py`. Declare a `ResourceSpec` and call mount functions:

```python
from src.api.common import BaseRouter
from src.api.common.resource_routes import (
    ResourceSpec, mount_create, mount_delete, mount_detail, mount_list, mount_update
)
from src.auth_config import current_active_user
from src.logic._authz import assert_owner_or_admin
from src.logic.<entity>.<entity>_processing import (
    <ENTITY>, handle_create_<entity>, handle_delete_<entity>, ...
)
from src.repositories.dependencies import get_<entity>_repository, get_audit_repository
from src.schemas.<entity>.<entity> import <entity>_create_adapter, <entity>_update_adapter

router = BaseRouter(router=APIRouter(prefix="/<entities>"))

<ENTITY>_SPEC = ResourceSpec(
    collection="<entities>",
    id_param="<entity>_id",
    repo_dep=get_<entity>_repository,
    audit_resource=<ENTITY>,
    read_user_dep=current_active_user,
    write_user_dep=current_active_user,
    write_authz=assert_owner_or_admin,
    create_adapter=<entity>_create_adapter,
    update_adapter=<entity>_update_adapter,
    read_to_dict=lambda obj: <Entity>Read.model_validate(obj).model_dump(mode="json"),
    list_template="<entities>/list.html",
    detail_template="<entities>/detail.html",
    form_template="<entities>/new.html",
)

mount_list(router, <ENTITY>_SPEC, handler=handle_list_<entity>)
mount_detail(router, <ENTITY>_SPEC, handler=handle_get_<entity>_detail)
mount_form(router, <ENTITY>_SPEC, handler=handle_get_<entity>_form, template="<entities>/new.html")
mount_form(router, <ENTITY>_SPEC, handler=handle_get_<entity>_edit_form, template="<entities>/edit.html", on_existing=True)
mount_create(router, <ENTITY>_SPEC, handler=handle_create_<entity>, audit_repo_dep=get_audit_repository)
mount_update(router, <ENTITY>_SPEC, handler=handle_update_<entity>, audit_repo_dep=get_audit_repository)
mount_delete(router, <ENTITY>_SPEC, handler=handle_delete_<entity>, audit_repo_dep=get_audit_repository)
```

2. Register the router in `src/main.py`. (Order matters when literal segments would shadow parametric ones — e.g. `/me/*` must be registered before the `/users` router.)

3. Add a colocated `test_<resource>.py`. The mount functions handle behavioral plumbing; tests verify resource-specific auth + handler behavior.

### Adding a sub-resource

Same pattern, plus `parent=PARENT_SPEC`. The mount walks the chain to build the path and inject parent ids:

```python
LICENSURE_SPEC = ResourceSpec(
    collection="licensures",
    id_param="licensure_id",
    repo_dep=get_provider_repository,
    audit_resource=LICENSURE,
    write_user_dep=current_active_user,
    write_authz=assert_owner_or_admin,
    create_adapter=licensure_create_adapter,
    update_adapter=licensure_update_adapter,
    read_to_dict=_licensure_read_dict,
    parent=PROVIDER_SPEC,
)
mount_create(router, LICENSURE_SPEC, handler=handle_create_licensure, audit_repo_dep=get_audit_repository)
mount_update(router, LICENSURE_SPEC, handler=handle_update_licensure, audit_repo_dep=get_audit_repository)
mount_delete(router, LICENSURE_SPEC, handler=handle_delete_licensure, audit_repo_dep=get_audit_repository)
```

The handler receives both `provider_id=` and `licensure_id=` (plus `payload=`, `repo=`, `audit_repo=`, `requesting_user=`).

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

The `me` router MUST be registered **before** the `users` router so that requests to `/users/me` match the literal `me` handler instead of being parsed as a UUID by the `/users/{user_id}` parametric route. More generally, any route that adds a literal segment under another resource's parametric path must be registered first.

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
