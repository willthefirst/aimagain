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

## Directory structure

**Core utility files:**

- `base_router.py` - Router wrapper that applies common decorators and configurations
- `responses.py` - Standardized response formatting for JSON and HTML
- `decorators.py` - Error handling and logging decorators applied to all routes
- `exceptions.py` - `APIException` subclasses (`NotFoundError`, `ForbiddenError`, ...) raised by logic, plus the fastapi-users → HTTP translator
- `forms.py` - HTTP-adapter primitives for form-encoded route bodies: `parse_form_to_payload(request)` (form → dict, lists for repeated keys) and `validate_or_422(adapter, payload_dict)` (run a `TypeAdapter`, translate `ValidationError` to 422 with `[{"loc","msg","type"}]`). Home for any HTTP-adapter primitive that two or more route modules would otherwise import from each other.

**Package infrastructure:**

- `__init__.py` - Exports all common utilities for easy import

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

**TODO** — no colocated tests yet. Add `test_*.py` here when modifying utilities in this directory (e.g. response helpers, error mapping). The route-level tests under `../routes/` exercise some of this behavior indirectly but should not be relied on as the only coverage.

## Related documentation

- [Routes Layer](../routes/README.md) - Route organization and patterns using common utilities
- [Logic Layer](../../logic/README.md) - Where the API exceptions in this package get raised
- [API Layer](../README.md) - Overall API layer architecture
