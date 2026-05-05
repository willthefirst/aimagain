# API routes: Domain-organized HTTP endpoints

The `api/routes/` directory contains **domain-specific route handlers** that define HTTP endpoints for the application, organized by business domain with consistent patterns for request handling, delegation to business logic, and response formatting.

> **Resource design contract — read first.** URL shape, lifecycle states, subresource conventions, and the rules for when to introduce one are defined in [`RESOURCE_GRAMMAR.md`](RESOURCE_GRAMMAR.md). Every resource in this codebase MUST conform to that grammar. This README describes *how routes are organized and wired*; the grammar describes *what URLs and lifecycles a resource MUST present*.

## Core philosophy: Thin routes with domain organization

Routes are **ultra-thin HTTP adapters** that handle request parsing, delegate to processing logic, and format responses while being organized by business domains for maintainability.

### What we do

- **Domain organization**: Routes grouped by business concepts (users, auth)
- **Thin route handlers**: Routes only handle HTTP concerns, business logic stays in processing layer
- **Consistent delegation**: All routes delegate to processing functions in the `logic/` layer
- **Standardized patterns**: BaseRouter provides consistent error handling and logging
- **Form and JSON support**: Handle both HTML form submissions and JSON API requests

**Example**: Clean route that delegates to processing logic:

```python
@router.get("/users")
async def list_users(
    request: Request,
    user: User = Depends(current_active_user),
    user_repo: UserRepository = Depends(get_user_repository),
):
    result = await handle_list_users(
        user_repo=user_repo,
        requesting_user=user,
    )
    return APIResponse.html_response(
        template_name="users/list.html",
        context=result,
        request=request,
    )
```

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

## Domain route organization matrix

| Route File         | Domain               | Primary Responsibilities         | Main Endpoints                                                                                                                  | Dependencies          |
| ------------------ | -------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| **users.py**       | User data            | User listing, detail, admin actions | `GET /users`, `GET /users/{id}`, `PUT /users/{id}/activation` (admin), `DELETE /users/{id}` (admin)                          | UserRepository        |
| **posts.py**       | Posts                | Post listing, detail, create, partial update, hard delete, and per-kind create/edit form pages | `GET /posts`, `GET /posts/form?kind={client_referral,provider_availability}`, `GET /posts/{id}`, `GET /posts/{id}/form`, `POST /posts`, `PATCH /posts/{id}`, `DELETE /posts/{id}` | PostRepository        |
| **me.py**          | Current user context | User profile, current-user JSON  | `GET /users/me`, `GET /users/me/profile`                                                                                        | Auth                  |
| **auth_routes.py** | Authentication API   | Login, register, password reset  | `/auth/*`                                                                                                                       | Authentication logic  |
| **auth_pages.py**  | Authentication UI    | Login, register forms            | `/login`, `/register`                                                                                                           | Authentication logic  |

## Directory structure

**Domain route files:**

- `users.py` - User listing and access
- `posts.py` - Post listing, detail, create, partial update, hard delete, and per-kind HTML form pages. `GET /posts/form?kind={client_referral,provider_availability}` selects the create-form template (`Literal` validator → 422 on unknown kinds); `GET /posts/{id}/form` selects the edit-form template from the persisted `post.kind`. `POST /posts` accepts a kind-discriminated body (`kind` required); `PATCH /posts/{id}` rejects payloads whose `kind` doesn't match the persisted post.
- `me.py` - Current user's profile

**Authentication routes:**

- `auth_routes.py` - JSON API endpoints for authentication
- `auth_pages.py` - HTML forms for authentication

**Package files:**

- `__init__.py` - Route exports and package configuration

## Implementation patterns

### Creating a new route file

1. **Create the route file** in `[domain].py`:

```python
import logging

from fastapi import APIRouter, Depends, Request

from src.api.common import APIResponse, BaseRouter
from src.auth_config import current_active_user
from src.logic.[domain]_processing import handle_create_[domain], handle_list_[domain]
from src.models import User
from src.repositories.dependencies import get_[domain]_repository
from src.repositories.[domain]_repository import [Domain]Repository

logger = logging.getLogger(__name__)

# Create APIRouter instance and wrap with BaseRouter
[domain]_router_instance = APIRouter()
router = BaseRouter(router=[domain]_router_instance)
```

2. **Add route handlers with delegation pattern**:

```python
@router.get("/[domain]")
async def list_[domain](
    request: Request,
    user: User = Depends(current_active_user),
    repo: [Domain]Repository = Depends(get_[domain]_repository),
):
    """Lists [domain] items by calling the logic handler."""
    items = await handle_list_[domain](repo, requesting_user=user)
    return APIResponse.html_response(
        template_name="[domain]/list.html",
        context={"items": items},
        request=request,
    )

@router.post("/[domain]")
async def create_[domain](
    data: [Domain]Create,
    user: User = Depends(current_active_user),
    repo: [Domain]Repository = Depends(get_[domain]_repository),
):
    """Creates [domain] item by calling the logic handler."""
    return await handle_create_[domain](data, user, repo)
```

3. **Register the routes** in main application:

```python
# In main.py or route registration
from src.api.routes import [domain]
app.include_router([domain].[domain]_router_instance, tags=["[domain]"])
```

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

The `me` router MUST be registered **before** the `users` router so that requests to `/users/me` match the literal `me` handler instead of being parsed as a UUID by the `/users/{user_id}` parametric route.

```python
# In main.py
from src.api.routes import (
    users,
    auth_routes,
    auth_pages,
    me,
)

app.include_router(auth_pages.auth_pages_api_router)
app.include_router(me.me_router_instance, tags=["me"])
app.include_router(users.users_api_router, tags=["users"])
```

### Route naming and organization

```python
# Consistent naming pattern
[domain]_router_instance = APIRouter()
router = BaseRouter(router=[domain]_router_instance)
```

The URL shape, HTTP method, and form-page conventions for every resource are defined in [`RESOURCE_GRAMMAR.md`](RESOURCE_GRAMMAR.md). Do not invent endpoint shapes here — follow the grammar.

## Tests

Colocated alongside the routes:

- `test_auth_routes.py` — registration, login, logout, password reset, session protection (covers `auth_routes.py` and `auth_pages.py`).
- `test_users.py` — `GET /users` listing behavior (covers `users.py`).
- `test_posts.py` — `GET /posts`, `GET /posts/{id}`, `POST /posts`, `PATCH /posts/{id}`, `DELETE /posts/{id}`, `GET /posts/form?kind={client_referral,provider_availability}`, and `GET /posts/{id}/form` (covers `posts.py`). Exercises every kind end-to-end: per-kind create/list/detail/edit-form/PATCH/DELETE, the kind-mismatch 400 on PATCH (asserts state-unchanged + no audit row), owner-or-admin authorization on PATCH and DELETE, the `extra="forbid"` scrub of `owner_id`, route-ordering checks, audit-row before/after assertions, the rejection of the retired `note` kind, and `_owner_actions.html` partial visibility on the detail page. Pact contract pair for the owner-actions Delete button lives under [`tests/test_contract/`](../../../tests/test_contract/README.md); per-kind create/edit-form contract pairs are deferred until the form schemas stabilize.

When adding a new route, add (or extend) a `test_*.py` file in this same directory. Shared fixtures (`test_client`, `authenticated_client`, `db_test_session_manager`, `logged_in_user`) come from [`tests/fixtures.py`](../../../tests/fixtures.py); user-construction helpers from [`tests/helpers.py`](../../../tests/helpers.py).

## Related documentation

- [API Common](../common/README.md) - Shared API utilities and BaseRouter
- [Logic Layer](../../logic/README.md) - Processing logic that routes delegate to
- [API Layer](../README.md) - Overall API layer architecture
