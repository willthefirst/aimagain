# API common: Shared utilities and standardized patterns

The `api/common/` directory contains **shared utilities** for the API layer, implementing standardized patterns for error handling, logging, response formatting, and route management that ensure consistency across all API endpoints.

## Core philosophy: Standardized API patterns

Common utilities provide **consistent behavior** across all API routes through decorators, response helpers, and error handling patterns that eliminate boilerplate and ensure uniform user experience.

### What we do

- **Standardized error handling**: Convert service exceptions to appropriate HTTP responses
- **Automatic logging**: Structured logging for all route calls with entry/exit/error tracking
- **Response formatting**: Consistent JSON and HTML response structures
- **BaseRouter wrapper**: Automatic application of common decorators and configurations
- **Exception mapping**: Clean mapping from business exceptions to HTTP status codes

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

**Routes -> Common Utilities -> Service Layer**

Common utilities handle concerns that span multiple routes and domains.

## Common utilities responsibility matrix

| Utility         | Purpose                | Responsibilities                      | Used By                  |
| --------------- | ---------------------- | ------------------------------------- | ------------------------ |
| **BaseRouter**  | Route standardization  | Apply decorators, manage dependencies | All route files          |
| **APIResponse** | Response formatting    | JSON/HTML responses, template context | All route handlers       |
| **Decorators**  | Cross-cutting concerns | Error handling, logging               | BaseRouter (automatic)   |
| **Exceptions**  | Error mapping          | Service -> HTTP exception translation | Error handling decorator |

## Directory structure

**Core utility files:**

- `base_router.py` - Router wrapper that applies common decorators and configurations
- `responses.py` - Standardized response formatting for JSON and HTML
- `decorators.py` - Error handling and logging decorators applied to all routes
- `exceptions.py` - Service exception to HTTP exception mapping

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

Service exceptions are automatically mapped to HTTP responses:

```python
# Service layer throws business exceptions
class [Entity]Service:
    async def create_entity(self, data):
        if not valid:
            raise BusinessRuleError("Validation failed")  # Business exception

# Route layer - exceptions automatically handled
@router.post("/[entities]")
async def create_entity(data: [Entity]Create):
    return await service.create_entity(data)
    # BusinessRuleError automatically becomes HTTP 400 Bad Request

# Exception mapping in exceptions.py
def handle_service_error(e: ServiceError):
    if isinstance(e, BusinessRuleError):
        raise BadRequestError(detail=e.message)  # HTTP 400
    elif isinstance(e, NotFoundError):
        raise NotFoundError(detail=e.message)    # HTTP 404
    # ... more mappings
```

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
async def list_users():
    try:
        return await service.list_users()
    except BusinessRuleError as e:
        return {"error": str(e)}  # Inconsistent format

# Good - automatic error handling
router = BaseRouter(router=APIRouter())

@router.get("/users")
async def list_users():
    return await service.list_users()
    # Errors automatically formatted consistently
```

### Issue: Missing logging for debugging

**Problem**: Hard to debug route issues without consistent logging
**Solution**: BaseRouter applies logging automatically

```python
# Bad - manual logging
@router.get("/users")
async def list_users():
    logger.info("Listing users")
    try:
        result = await service.list_users()
        logger.info("Users listed successfully")
        return result
    except Exception as e:
        logger.error(f"Failed to list users: {e}")
        raise

# Good - automatic logging
router = BaseRouter(router=APIRouter())

@router.get("/users")  # Logging automatic
async def list_users():
    return await service.list_users()
```

### Issue: Mixed response formats

**Problem**: Some routes return raw data, others use response objects
**Solution**: Always use APIResponse for consistency

```python
# Bad - mixed response formats
@router.get("/users")
async def list_users():
    return users  # Raw data

@router.get("/data")
async def get_data():
    return {"data": data, "status": "ok"}  # Custom format

# Good - consistent response format
@router.get("/users")
async def list_users():
    users = await get_users()
    return APIResponse.success(data=users)

@router.get("/data")
async def get_data():
    data = await get_data()
    return APIResponse.success(data=data)
```

## Available decorators and utilities

### Decorators (applied automatically by baserouter)

```python
@log_route_call        # Logs entry, exit, and errors
@handle_route_errors   # Maps service exceptions to HTTP responses
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
# HTTP exception classes
NotFoundError(detail)      # 404
BadRequestError(detail)    # 400
UnauthorizedError(detail)  # 401
ForbiddenError(detail)     # 403
InternalServerError(detail) # 500

# Service exception mapping
handle_service_error(service_exception) -> HTTPException
```

## Related documentation

- [Routes Layer](../routes/README.md) - Route organization and patterns using common utilities
- [Services Layer](../../services/README.md) - Service layer exceptions that get mapped to HTTP responses
- [API Layer](../README.md) - Overall API layer architecture
