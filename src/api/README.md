---
description:
globs:
alwaysApply: false
---

# API layer: HTTP routes and request handling

The `api/` directory contains all HTTP-related code, organized around **domain-driven routing** with consistent patterns for error handling, logging, and response formatting.

## 🎯 Core philosophy: Thin routes with standardized patterns

API routes are **thin wrappers** that delegate business logic to services while providing consistent HTTP concerns like validation, error handling, and response formatting.

### What we do ✅

- **Domain-organized routes**: Routes grouped by business domain (conversations, users, auth)
- **Standardized router patterns**: BaseRouter provides consistent decorators and error handling
- **Delegated business logic**: Routes call processing logic, not implement it
- **Consistent response formats**: APIResponse class standardizes JSON and HTML responses
- **Automatic error handling**: Decorators catch and transform service exceptions to HTTP responses

**Example**: Clean route that delegates to processing logic:

```python
@router.post("/conversations")
async def create_conversation(
    invitee_username: str = Form(...),
    initial_message: str = Form(...),
    user: User = Depends(current_active_user),
    conv_service: ConversationService = Depends(get_conversation_service),
):
    conversation = await handle_create_conversation(
        invitee_username=invitee_username,
        initial_message=initial_message,
        creator_user=user,
        conv_service=conv_service,
    )
    return RedirectResponse(url=f"/conversations/{conversation.slug}")
```

### What we don't do ❌

- **Business logic in routes**: Complex validation and processing stays in services/logic layers
- **Direct database access**: Routes never touch repositories or sessions directly
- **Inconsistent error handling**: All routes use standardized error decorators
- **Raw APIRouter usage**: Always wrap with BaseRouter for consistent patterns

**Example**: Don't implement business logic in routes:

```python
# ❌ Wrong - business logic in route
@router.post("/conversations")
async def create_conversation(data: dict, session: AsyncSession = Depends()):
    # Complex validation here
    if not data.get("title"):
        raise HTTPException(400, "Title required")
    # Database operations here
    conv = Conversation(**data)
    session.add(conv)
    await session.commit()
    return conv

# ✅ Correct - delegate to processing layer
@router.post("/conversations")
async def create_conversation(
    data: ConversationCreate,
    conv_service: ConversationService = Depends()
):
    return await handle_create_conversation(data, conv_service)
```

## 🏗️ architecture: Domain-driven routing

**HTTP Request → Route → Processing Logic → Service → Response**

Routes are organized by domain and use consistent patterns for common concerns.

## 📋 API organization matrix

| Component      | Purpose                         | Example Files              | Dependencies               |
| -------------- | ------------------------------- | -------------------------- | -------------------------- |
| **Routes**     | HTTP endpoints by domain        | `routes/conversations.py`  | Processing logic, Services |
| **Common**     | Shared utilities and patterns   | `common/base_router.py`    | FastAPI, Decorators        |
| **Processing** | Request/response transformation | `../logic/*_processing.py` | Services, Schemas          |
| **Responses**  | Standardized response formats   | `common/responses.py`      | Templates, JSON            |

## 📁 Directory structure

**Core API files:**

- `routes/` - Domain-organized HTTP endpoints
  - `conversations.py` - Conversation management endpoints
  - `users.py` - User-related endpoints
  - `auth_routes.py` - Authentication API endpoints
  - `auth_pages.py` - Authentication web pages
  - `participants.py` - Participant management
  - `me.py` - Current user endpoints

**Common utilities:**

- `common/` - Shared API patterns and utilities
  - `base_router.py` - Router wrapper with standard decorators
  - `decorators.py` - Error handling and logging decorators
  - `exceptions.py` - Exception to HTTP status mapping
  - `responses.py` - Standardized response formats

## 🔧 Implementation patterns

### Creating a new route file

1. **Create domain router** in `routes/[domain].py`:

```python
from fastapi import APIRouter, Depends
from src.api.common import BaseRouter
from src.services.dependencies import get_[domain]_service

# Create standard apirouter and wrap with baserouter
[domain]_api_router = APIRouter()
router = BaseRouter(router=[domain]_api_router, default_tags=["[domain]"])
```

2. **Add route handlers**:

```python
@router.get("/[domain]")
async def list_[domain](
    service: [Domain]Service = Depends(get_[domain]_service)
):
    return await handle_list_[domain](mdc:service)

@router.post("/[domain]")
async def create_[domain](
    data: [Domain]Create,
    service: [Domain]Service = Depends(get_[domain]_service)
):
    return await handle_create_[domain](mdc:data, service)
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

Errors are handled automatically by decorators:

```python
# Service exceptions are automatically caught and converted to HTTP responses
@router.post("/conversations")
async def create_conversation(
    data: ConversationCreate,
    service: ConversationService = Depends()
):
    # If service raises ConversationNotFoundError -> 404
    # If service raises NotAuthorizedError -> 403
    # If service raises BusinessRuleError -> 400
    return await service.create_conversation(data)
```

## 🚨 Common issues and solutions

### Issue: Business logic creeping into routes

**Problem**: Routes become complex with validation, database operations, etc.
**Solution**: Keep routes thin - delegate to processing logic in `../logic/` directory

```python
# ❌ Wrong - complex logic in route
@router.post("/conversations")
async def create_conversation(title: str, user: User = Depends()):
    if len(title) < 3:
        raise HTTPException(400, "Title too short")
    if await conversation_exists(title):
        raise HTTPException(409, "Conversation exists")
    # ... more logic

# ✅ Correct - delegate to processing logic
@router.post("/conversations")
async def create_conversation(
    data: ConversationCreate,
    user: User = Depends(),
    service: ConversationService = Depends()
):
    return await handle_create_conversation(data, user, service)
```

### Issue: Inconsistent error handling

**Problem**: Some routes handle errors differently than others
**Solution**: Always use BaseRouter which applies standard error decorators

```python
# ❌ Wrong - manual error handling
@APIRouter().post("/endpoint")
async def endpoint():
    try:
        result = await service.do_something()
        return {"data": result}
    except SomeError as e:
        raise HTTPException(400, str(e))

# ✅ Correct - automatic error handling via BaseRouter
@router.post("/endpoint")  # router is BaseRouter instance
async def endpoint(service: Service = Depends()):
    return await service.do_something()  # Errors automatically handled
```

### Issue: Response format inconsistency

**Problem**: Different routes return different response formats
**Solution**: Use APIResponse class for consistent formatting

```python
# ❌ Wrong - inconsistent response formats
@router.get("/data")
async def get_data():
    return {"result": data}  # Raw dict

@router.get("/other")
async def get_other():
    return JSONResponse({"status": "ok", "data": data})  # Different format

# ✅ Correct - consistent response format
@router.get("/data")
async def get_data():
    return APIResponse.success(data, "Data retrieved")

@router.get("/other")
async def get_other():
    return APIResponse.success(data, "Other data retrieved")
```

## 📚 Related documentation

- [Services Layer Documentation](services/README.md) - Business logic called by routes
- [Processing Logic Documentation](../logic/README.md) - Request/response transformation
- [Schemas Documentation](../schemas/README.md) - Request/response validation
- [Main Architecture](../README.md) - How API fits in overall architecture
