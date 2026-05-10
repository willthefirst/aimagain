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

## Directory structure

**Core utility files:**

- `base_router.py` - Router wrapper that applies common decorators and configurations
- `responses.py` - Standardized response formatting for JSON and HTML
- `decorators.py` - Error handling and logging decorators applied to all routes
- `exceptions.py` - `APIException` subclasses (`NotFoundError`, `ForbiddenError`, ...) raised by logic, plus the fastapi-users → HTTP translator
- `forms.py` - HTTP-adapter primitives for request bodies: `parse_form_to_payload(request)` (form → dict, lists for repeated keys), `validate_or_422(adapter, payload_dict)` (run a `TypeAdapter`, translate `ValidationError` to 422 with `[{"loc","msg","type"}]`), and the back-to-back wrappers `parse_and_validate_form` / `parse_and_validate_json` (form-encoded vs. JSON body — state-axis subresources use the JSON variant). Home for any HTTP-adapter primitive that two or more route modules would otherwise import from each other.
- `projections.py` - `project_view(obj, *, public_fields, actor, private_fields=(), private_field_predicate=None)` builds a dict of `public_fields` from `obj` and conditionally appends `private_fields` when `private_field_predicate(actor, obj)` is true. Used by handlers that gate fields per viewer (today: user detail, where `email` / `is_active` / `is_verified` are visible only to the user themselves or an admin). Defense in depth alongside template-level guards: omitting keys at projection time means a forgotten `{% if %}` cannot re-leak. `ResourceSpec.private_fields` / `private_field_predicate` store the same primitives as declarative metadata so future cross-layer readers (JSON endpoint, audit snapshot, OpenAPI doc) can read the rule without rediscovering it.
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
| `mount_related_list` | Landed (slice 9 / #254) | `users` (GET /{id}/providers) |
| `mount_state_axis` | Landed (#302) | `users` (PUT /{id}/activation) |
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
    extra_repo_deps=(get_provider_repository,),
    singleton_alias=("me", current_active_user),
)
# Mounts BOTH GET /users/{user_id} AND GET /users/me; same handler with
# user_id=<URL> or <session.id>.

mount_related_list(
    router, parent_spec=USER_SPEC, child_spec=PROVIDER_SPEC,
    handler=handle_list_user_providers,
    template="users/providers_list.html",
    extra_repo_deps=(get_user_repository,),
    singleton_alias=("me", current_active_user),
)
# Mounts /users/{user_id}/providers AND /users/me/providers.
```

The mount registers the alias path BEFORE the parametric one within the same router so FastAPI matches `/users/me` against the literal alias instead of trying to parse `me` as a UUID against `/users/{user_id}`.

### Per-mount references

Per-mount docstrings in `resource_routes.py` are the canonical reference for required spec fields and exact handler kwargs.

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
