# API routes: Domain-organized HTTP endpoints

The `api/routes/` directory contains **domain-specific route handlers** that define HTTP endpoints for the application, organized by business domain with consistent patterns for request handling, delegation to business logic, and response formatting.

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

# Good - delegate to processing layer
@router.post("/[entities]")
async def create_entity(
    data: [Entity]Create,
    service: [Entity]Service = Depends()
):
    return await handle_create_entity(data, service)
```

## Architecture: Domain-driven route organization

**HTTP Request -> Route Handler -> Processing Logic -> Service Layer -> Response**

Routes are organized by domain with consistent delegation patterns.

## Domain route organization matrix

| Route File         | Domain               | Primary Responsibilities         | Main Endpoints        | Dependencies          |
| ------------------ | -------------------- | -------------------------------- | --------------------- | --------------------- |
| **users.py**       | User data            | User listings                    | `/users`              | UserRepository        |
| **me.py**          | Current user context | User profile                     | `/users/me/profile`   | Auth                  |
| **auth_routes.py** | Authentication API   | Login, register, password reset  | `/auth/*`             | Authentication logic  |
| **auth_pages.py**  | Authentication UI    | Login, register forms            | `/login`, `/register` | Authentication logic  |

## Directory structure

**Domain route files:**

- `users.py` - User listing and access
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
from src.logic.[domain]_processing import handle_[action]
from src.services.dependencies import get_[domain]_service

logger = logging.getLogger(__name__)

# Create apirouter instance and wrap with baserouter
[domain]_router_instance = APIRouter()
router = BaseRouter(router=[domain]_router_instance)
```

2. **Add route handlers with delegation pattern**:

```python
@router.get("/[domain]")
async def list_[domain](
    request: Request,
    service: [Domain]Service = Depends(get_[domain]_service),
):
    """Lists [domain] items by calling the processing handler."""
    items = await handle_list_[domain](service=service)
    return APIResponse.html_response(
        template_name="[domain]/list.html",
        context={"items": items},
        request=request,
    )

@router.post("/[domain]")
async def create_[domain](
    data: [Domain]Create,
    user: User = Depends(current_active_user),
    service: [Domain]Service = Depends(get_[domain]_service),
):
    """Creates [domain] item by calling the processing handler."""
    item = await handle_create_[domain](
        data=data,
        user=user,
        service=service,
    )
    return item
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

```python
# In main.py
from src.api.routes import (
    users,
    auth_routes,
    auth_pages,
    me,
)

app.include_router(users.users_router_instance, tags=["users"])
app.include_router(auth_routes.auth_api_router_instance, prefix="/auth", tags=["auth-api"])
app.include_router(auth_pages.auth_pages_router_instance, tags=["auth-pages"])
app.include_router(me.me_router_instance, prefix="/users/me", tags=["me"])
```

### Route naming and organization

```python
# Consistent naming pattern
[domain]_router_instance = APIRouter()
router = BaseRouter(router=[domain]_router_instance)

# Consistent endpoint naming
@router.get("/[domain]")           # List
@router.get("/[domain]/new")       # New form
@router.get("/[domain]/{id}")      # Detail
@router.post("/[domain]")          # Create
@router.put("/[domain]/{id}")      # Update
@router.delete("/[domain]/{id}")   # Delete
```

## Related documentation

- [API Common](../common/README.md) - Shared API utilities and BaseRouter
- [Logic Layer](../../logic/README.md) - Processing logic that routes delegate to
- [API Layer](../README.md) - Overall API layer architecture
