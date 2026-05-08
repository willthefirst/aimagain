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
class APIResponse:
    @staticmethod
    def create_user_response(user):
        # Business logic about user formatting
        if user.is_admin:
            return {"status": "admin", "data": {...}}

# Good - generic response formatting only
class APIResponse:
    @staticmethod
    def success(data: Any, message: str = "Success") -> JSONResponse:
        return JSONResponse(
            content={"status": "success", "message": message, "data": data}
        )
```

## Architecture: Cross-cutting concerns layer

**Routes -> Common Utilities -> Logic Layer**

Common utilities handle concerns that span multiple routes and domains.

## Common utilities responsibility matrix

| Utility         | Purpose                | Responsibilities                                                | Used By                  |
| --------------- | ---------------------- | --------------------------------------------------------------- | ------------------------ |
| **BaseRouter**  | Route standardization  | Apply decorators, manage dependencies                           | All route files          |
| **APIResponse** | Response formatting    | JSON/HTML responses, template context                           | All route handlers       |
| **Decorators**  | Cross-cutting concerns | Error handling, logging                                         | BaseRouter (automatic)   |
| **Exceptions**  | Error vocabulary       | API exception classes raised by logic; fastapi-users translator | Logic handlers, decorator |
| **Forms**       | Form-encoded request glue | `parse_form_to_payload` and `validate_or_422`                | Route handlers that accept form-encoded bodies |
| **resource_routes** | Unified `ResourceSpec` grammar | Declare a resource once, opt into the operations to expose via `mount_*`; sub-resources nest via `parent=` | Route files for any CRUD-shaped resource (top-level and sub-resource) |

## Directory structure

**Core utility files:**

- `base_router.py` - Router wrapper that applies common decorators and configurations
- `responses.py` - Standardized response formatting for JSON and HTML
- `decorators.py` - Error handling and logging decorators applied to all routes
- `exceptions.py` - `APIException` subclasses (`NotFoundError`, `ForbiddenError`, ...) raised by logic, plus the fastapi-users → HTTP translator
- `forms.py` - HTTP-adapter primitives for form-encoded route bodies: `parse_form_to_payload(request)` (form → dict, lists for repeated keys) and `validate_or_422(adapter, payload_dict)` (run a `TypeAdapter`, translate `ValidationError` to 422 with `[{"loc","msg","type"}]`). Home for any HTTP-adapter primitive that two or more route modules would otherwise import from each other.
- `resource_routes.py` - Unified `ResourceSpec` + opt-in `mount_*` grammar (covers top-level *and* sub-resource CRUD via `parent=`). See [Unified resource grammar](#unified-resource-grammar) below.

**Package infrastructure:**

- `__init__.py` - Exports all common utilities for easy import

## Unified resource grammar

`resource_routes.py` is the in-progress home for a unified `ResourceSpec` + opt-in `mount_*` grammar that covers every CRUD-shaped route. It's being built incrementally in 10 slices (see issues with the `refactor` label whose titles start with "Slice"); today only `mount_delete` is wired up and exercised by `users.py`.

### The shape

A resource declares a single `ResourceSpec` describing its **identity** — collection name, id param, primary repo, audit bundle, auth deps, schemas, templates, redirect targets. The route file then **opts in** to the operations it wants to expose by calling the corresponding mount function:

```python
from src.api.common.resource_routes import ResourceSpec, mount_delete
from src.logic.users.user_processing import USER, handle_delete_user

users_api_router = APIRouter(prefix="/users")
router = BaseRouter(router=users_api_router, default_tags=["users"])

USER_SPEC = ResourceSpec(
    collection="users",
    id_param="user_id",
    repo_dep=get_user_repository,
    audit_resource=USER,                  # AuditedResource bundle from logic
    read_user_dep=current_active_user,
    write_user_dep=current_admin_user,
)

mount_delete(
    router,
    USER_SPEC,
    handler=handle_delete_user,
    audit_repo_dep=get_audit_repository,
)
```

### Why this shape

- **Opt-in mounts.** A read-only resource simply doesn't call `mount_create`/`mount_update`/`mount_delete` — there's no `read_only=True` flag because *not calling the mount* is the cleanest way to express "don't expose this verb." A backend-only resource (e.g. an async verification record written by a worker) still declares `audit_resource` so the worker can call `mutate(...)`, but the route file mounts only `mount_list` / `mount_detail`.
- **Spec is identity, mounts are operations.** Adding a new mount function (`mount_list`, `mount_create`, ...) doesn't change `ResourceSpec`'s shape for resources that don't use it — defaults are `None`. The dataclass grows fields incrementally as new mounts land.
- **Sub-resources nest via `parent`.** A child `ResourceSpec` carrying `parent=parent_spec` produces paths like `/providers/{provider_id}/licensures/{licensure_id}` — same `mount_create`/`mount_update`/`mount_delete` functions as top-level resources. The router's prefix is the topmost ancestor's collection (e.g. `APIRouter(prefix="/providers")`); the mount walks the parent chain to build the rest of the path. Handler kwargs include every parent id by its declared `id_param` name (`provider_id=...`, then the resource's own id).
- **Polymorphic resources via handler-driven knobs.** Posts dispatch templates by `kind`; the route doesn't need to. The handler returns a `template_name` in its context dict and the mount honors it. This keeps the spec's shape stable even when the resource's behavior is polymorphic — `mount_form` for `GET /posts/{id}/form` uses this in slice 7. The grammar isn't infinitely flexible though: `GET /posts/form?kind=X` (where the *query param* picks the template) stays bespoke because mount_form's contract doesn't carry query params, and widening it for one case would bloat every spec.

### Handler signatures

Mount functions invoke handlers with a fixed shape so the spec can plumb args generically. Every handler the mounts call expects:

- **`<id_param>=<UUID>`** for routes with an id in the path (detail/update/delete), under the per-resource kwarg name declared in the spec (`user_id`, `post_id`, ...).
- **`repo=<primary repo>`** for the resource's primary repository, sourced from `spec.repo_dep`.
- **`audit_repo=<AuditRepository>`** for mutation handlers, sourced from `audit_repo_dep` passed to the mount call (it's a layer-wide concern, not a per-resource knob).
- **`requesting_user=<User>`** for any handler that gates on auth, sourced from `spec.read_user_dep` or `spec.write_user_dep`.
- **`payload=<validated body>`** for create/update handlers (slices 6–7).

Secondary repos (e.g. `user_repo: UserRepository` in the multi-repo `handle_list_user_providers`) keep their typed name per the [logic-layer convention](../../logic/README.md#handler-kwarg-naming) and arrive via `spec.extra_repo_deps`.

### What's mounted today

| Mount | Status | Resources using it |
| --- | --- | --- |
| `mount_delete` | Landed (slice 3 / #248) | `users` (DELETE) |
| `mount_list` / `mount_detail` | Landed (slice 4 / #249) | `users` (GET / and GET /{id}) |
| `mount_form` | Landed (slice 5 / #250) | `providers` (GET /form, GET /{id}/form); `posts` (edit form via handler-returned template_name) |
| `mount_create` / `mount_update` | Landed (slice 6 / #251) | `providers`, `posts`, `licensures`, `educations`, `certifications` |
| `mount_related_list` | Slice 9 / #254 | — |
| Sub-resource via `parent=` | Landed (slice 8 / #253) | `licensures`, `educations`, `certifications` (under providers) |

### Multi-repo handlers: `extra_repo_deps`

Some handlers need more than the resource's primary repo — e.g. `handle_get_user_detail` takes both the user repo (the primary) and the provider repo (to embed the owned-providers list on the user-detail page). The mount that needs them passes them via the `extra_repo_deps` kwarg:

```python
mount_detail(
    router,
    USER_SPEC,
    handler=handle_get_user_detail,
    extra_repo_deps=(get_provider_repository,),
)
```

The mount derives the kwarg name from the dep callable: `get_provider_repository` → `provider_repo` (strip `get_` prefix, replace `_repository` suffix with `_repo`). The handler must take the same name. If the dep doesn't follow the `get_<entity>_repository` convention, the mount raises at registration time — silent name-mismatches would be a request-time bug.

`extra_repo_deps` is per-mount, not per-spec, because different mounts on the same resource often need different extras (the list view doesn't need provider_repo even though the detail view does).

Per-mount docstrings in `resource_routes.py` are the canonical reference for required spec fields and exact handler kwargs.

### What's *not* meant for this grammar

The grammar fits resource-shaped routes. It's deliberately **not** a home for:

- **Auth flows** — register/login/verify/reset-password live in `auth_routes.py` / `auth_pages.py`. State-machine semantics, not CRUD.
- **`/me/*` singletons** — no parent id, session-sourced. Stays bespoke (slice 9 decision).
- **State-mutation actions like `PUT /users/{id}/activation`** — idempotent set with `HX-Refresh`, not partial edit with `HX-Redirect`. Doesn't match `mount_update` semantics.
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

### Apiresponse pattern for consistent formatting

Use APIResponse for all response formatting:

```python
from src.api.common import APIResponse

# JSON API responses
@router.get("/api/users")
async def list_users_api():
    users = await get_users()
    return APIResponse.success(
        data=users,
        message="Users retrieved successfully"
    )

# HTML template responses
@router.get("/users")
async def list_users_page(request: Request):
    users = await get_users()
    return APIResponse.html_response(
        template_name="users/list.html",
        context={"users": users},
        request=request
    )

# Error responses (usually automatic via decorators)
return APIResponse.error(
    message="Invalid data",
    status_code=400,
    code="INVALID_DATA"
)
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
# Bad - mixed response formats
@router.get("/users")
async def list_users(user_repo: UserRepository = Depends(get_user_repository)):
    return await handle_list_users(user_repo)  # Raw data

@router.get("/data")
async def get_data():
    return {"data": data, "status": "ok"}  # Custom format

# Good - consistent response format
@router.get("/users")
async def list_users(user_repo: UserRepository = Depends(get_user_repository)):
    users = await handle_list_users(user_repo)
    return APIResponse.success(data=users)

@router.get("/data")
async def get_data():
    data = await fetch_data()
    return APIResponse.success(data=data)
```

## Available decorators and utilities

### Decorators (applied automatically by baserouter)

```python
@log_route_call        # Logs entry, exit, and errors
@handle_route_errors   # Passes HTTPException through; translates fastapi-users; 500 for the rest
```

### Response utilities

```python
# JSON responses
APIResponse.success(data, message="Success", status_code=200)
APIResponse.error(message, status_code=400, code=None)

# HTML responses
APIResponse.html_response(template_name, context, request)
```

### Exception classes

```python
# APIException subclasses raised directly by logic handlers
NotFoundError(detail)       # 404
BadRequestError(detail)     # 400
UnauthorizedError(detail)   # 401
ForbiddenError(detail)      # 403
InternalServerError(detail) # 500

# fastapi-users exception translator (called by the decorator)
handle_fastapi_users_error(fastapi_users_exception) -> APIException
```

## Tests

Colocated tests cover the helpers in this directory:

- `test_responses.py` — `APIResponse`, `created_response`, `updated_response`, `deleted_response`, `refreshed_response`.
- `test_subresource_routes.py` — `SubresourceSpec` + `register_subresource_routes` (slice 8 / #253 folds this into `resource_routes`).
- `test_resource_routes.py` — `ResourceSpec` + per-mount tests. Add a test here whenever a new mount function lands or an existing one grows a knob.

Route-level tests under `../routes/` exercise the mounts indirectly via the resources that use them; the unit tests here cover spec validation, error handling at mount time, and the path-param wiring that the route-level tests can't easily isolate.

## Related documentation

- [Routes Layer](../routes/README.md) - Route organization and patterns using common utilities
- [Logic Layer](../../logic/README.md) - Where the API exceptions in this package get raised
- [API Layer](../README.md) - Overall API layer architecture
