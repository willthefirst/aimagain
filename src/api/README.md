# API layer: HTTP routes and request handling

The `api/` directory contains all HTTP-related code, organized around **domain-driven routing** with consistent patterns for error handling, logging, and response formatting.

## Core philosophy: Thin routes with standardized patterns

API routes are **thin wrappers** that delegate business logic to services while providing consistent HTTP concerns like validation, error handling, and response formatting.

### What we do

- **Domain-organized routes**: Routes grouped by business domain (users, auth)
- **Standardized router patterns**: BaseRouter provides consistent decorators and error handling
- **Delegated business logic**: Routes call processing logic, not implement it
- **Consistent response formats**: APIResponse class standardizes JSON and HTML responses
- **Automatic error handling**: Decorators catch and transform service exceptions to HTTP responses

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

- **Business logic in routes**: Complex validation and processing stays in the `logic/` layer
- **Direct database access**: Routes never touch repositories or sessions directly
- **Inconsistent error handling**: All routes use standardized error decorators
- **Raw APIRouter usage**: Always wrap with BaseRouter for consistent patterns

**Example**: Don't implement business logic in routes:

```python
# Bad - business logic in route
@router.post("/[entities]")
async def create_entity(data: dict, session: AsyncSession = Depends()):
    if not data.get("name"):
        raise HTTPException(400, "Name required")
    entity = [Entity](**data)
    session.add(entity)
    await session.commit()
    return entity

# Good - delegate to logic handler
@router.post("/[entities]")
async def create_entity(
    data: [Entity]Create,
    user: User = Depends(current_active_user),
    repo: [Entity]Repository = Depends(get_[entity]_repository),
):
    return await handle_create_entity(data, user, repo)
```

## Architecture: Domain-driven routing

**HTTP Request -> Route -> Logic Handler -> Repository -> Response**

Routes are organized by domain and use consistent patterns for common concerns.

## Layer organization

- `routes/` — HTTP endpoint definitions, one file per resource. See [`routes/README.md`](routes/README.md) for the route organization contract and the URL grammar that every resource follows ([`routes/RESOURCE_GRAMMAR.md`](routes/RESOURCE_GRAMMAR.md)).
- `common/` — shared API infrastructure: `BaseRouter` (auto-applied error handling + logging decorators), `APIException` subclasses (`NotFoundError`, `ForbiddenError`, etc.) raised by logic and passed through to FastAPI, the fastapi-users error translator, and the standardized `APIResponse` helpers. See [`common/README.md`](common/README.md).

## Implementation patterns

### Creating a new route file

1. **Create domain router** in `routes/[domain].py`:

```python
from fastapi import APIRouter, Depends

from src.api.common import BaseRouter
from src.auth_config import current_active_user
from src.logic.[domain]_processing import handle_create_[domain], handle_list_[domain]
from src.models import User
from src.repositories.dependencies import get_[domain]_repository
from src.repositories.[domain]_repository import [Domain]Repository

# Create standard APIRouter and wrap with BaseRouter
[domain]_api_router = APIRouter()
router = BaseRouter(router=[domain]_api_router, default_tags=["[domain]"])
```

2. **Add route handlers**:

```python
@router.get("/[domain]")
async def list_[domain](
    user: User = Depends(current_active_user),
    repo: [Domain]Repository = Depends(get_[domain]_repository),
):
    return await handle_list_[domain](repo, requesting_user=user)

@router.post("/[domain]")
async def create_[domain](
    data: [Domain]Create,
    user: User = Depends(current_active_user),
    repo: [Domain]Repository = Depends(get_[domain]_repository),
):
    return await handle_create_[domain](data, user, repo)
```

3. **Register in main.py**:

```python
from src.api.routes import [domain]
app.include_router([domain].[domain]_api_router, tags=["[domain]"])
```

### Baserouter pattern

All routes use BaseRouter for consistent behavior:

```python
from src.api.common import BaseRouter

# Wrap apirouter with baserouter
router = BaseRouter(
    router=APIRouter(),
    default_tags=["domain"],
    default_dependencies=[Depends(some_common_dependency)]
)

# Routes automatically GET:
# - error handling decorator
# - logging decorator
# - common tags and dependencies
@router.get("/endpoint")
async def endpoint_handler():
    # Route logic here
    pass
```

### Response patterns

Use APIResponse for consistent formatting:

```python
from src.api.common import APIResponse

# JSON API responses
@router.get("/api/data")
async def get_data():
    data = await service.get_data()
    return APIResponse.success(data, "Data retrieved successfully")

# HTML page responses
@router.get("/pages/data")
async def get_data_page(request: Request):
    data = await service.get_data()
    return APIResponse.html_response(
        template_name="data/list.html",
        context={"data": data},
        request=request
    )
```

### Error handling pattern

Logic handlers raise the API exception classes directly; the decorator passes them through to FastAPI:

```python
# logic/<entity>_processing.py raises APIException subclasses directly.
@router.post("/[entities]")
async def create_entity(
    data: [Entity]Create,
    user: User = Depends(current_active_user),
    repo: [Entity]Repository = Depends(get_[entity]_repository),
):
    # Inside handle_create_entity:
    #   raise NotFoundError(...)   → 404
    #   raise ForbiddenError(...)  → 403
    #   raise BadRequestError(...) → 400
    return await handle_create_entity(data, user, repo)
```

## Common issues and solutions

### Issue: Business logic creeping into routes

**Problem**: Routes become complex with validation, database operations, etc.
**Solution**: Keep routes thin - delegate to processing logic in `../logic/` directory

```python
# Bad - complex logic in route
@router.post("/[entities]")
async def create_entity(name: str, user: User = Depends()):
    if len(name) < 3:
        raise HTTPException(400, "Name too short")
    if await entity_exists(name):
        raise HTTPException(409, "Entity exists")

# Good - delegate to logic handler
@router.post("/[entities]")
async def create_entity(
    data: [Entity]Create,
    user: User = Depends(current_active_user),
    repo: [Entity]Repository = Depends(get_[entity]_repository),
):
    return await handle_create_entity(data, user, repo)
```

### Issue: Inconsistent error handling

**Problem**: Some routes handle errors differently than others
**Solution**: Always use BaseRouter which applies standard error decorators

```python
# Bad - manual error handling
@APIRouter().post("/endpoint")
async def endpoint():
    try:
        result = await service.do_something()
        return {"data": result}
    except SomeError as e:
        raise HTTPException(400, str(e))

# Good - automatic error handling via BaseRouter
@router.post("/endpoint")  # router is BaseRouter instance
async def endpoint(service: Service = Depends()):
    return await service.do_something()  # Errors automatically handled
```

### Issue: Response format inconsistency

**Problem**: Different routes return different response formats
**Solution**: Use APIResponse class for consistent formatting

```python
# Bad - inconsistent response formats
@router.get("/data")
async def get_data():
    return {"result": data}  # Raw dict

@router.get("/other")
async def get_other():
    return JSONResponse({"status": "ok", "data": data})  # Different format

# Good - consistent response format
@router.get("/data")
async def get_data():
    return APIResponse.success(data, "Data retrieved")

@router.get("/other")
async def get_other():
    return APIResponse.success(data, "Other data retrieved")
```

## Tests

API behavior is exercised by route-level tests colocated under [`routes/`](routes/) (e.g. `routes/test_auth_routes.py`, `routes/test_users.py`). There is no test file at this directory level — tests live next to the specific routes they cover.

## Related documentation

- [Logic Layer Documentation](../logic/README.md) - Business logic, orchestration, transaction commits
- [Schemas Documentation](../schemas/README.md) - Request/response validation
- [Main Architecture](../README.md) - How API fits in overall architecture
