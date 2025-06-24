# API routes: Domain-organized HTTP endpoints

The `api/routes/` directory contains **domain-specific route handlers** that define HTTP endpoints for the Aimagain chat application, organized by business domain with consistent patterns for request handling, delegation to business logic, and response formatting.

## 🎯 Core philosophy: Thin routes with domain organization

Routes are **ultra-thin HTTP adapters** that handle request parsing, delegate to processing logic, and format responses while being organized by business domains for maintainability.

### What we do ✅

- **Domain organization**: Routes grouped by business concepts (conversations, users, auth, participants)
- **Thin route handlers**: Routes only handle HTTP concerns, business logic stays in processing layer
- **Consistent delegation**: All routes delegate to processing functions in the `logic/` layer
- **Standardized patterns**: BaseRouter provides consistent error handling and logging
- **Form and JSON support**: Handle both HTML form submissions and JSON API requests

**Example**: Clean route that delegates to processing logic:

```python
@router.post("/conversations")
async def create_conversation(
    invitee_username: str = Form(...),
    initial_message: str = Form(...),
    user: User = Depends(current_active_user),
    conv_service: ConversationService = Depends(get_conversation_service),
):
    """Handles the form submission by calling the processing logic."""
    conversation = await handle_create_conversation(
        invitee_username=invitee_username,
        initial_message=initial_message,
        creator_user=user,
        conv_service=conv_service,
    )

    redirect_url = f"/conversations/{conversation.slug}"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)
```

### What we don't do ❌

- **Business logic in routes**: Complex validation, business rules, and processing stays in logic layer
- **Direct database access**: Routes never call repositories or database sessions directly
- **Mixed concerns**: HTTP handling separate from business logic and data access
- **Inconsistent error handling**: All routes use BaseRouter for standardized error responses

**Example**: Don't implement business logic in routes:

```python
# ❌ Wrong - business logic in route
@router.post("/conversations")
async def create_conversation(data: dict, session: AsyncSession = Depends()):
    # Complex validation logic here
    if not data.get("invitee_username"):
        raise HTTPException(400, "Username required")

    # Database operations here
    invitee = await session.execute(select(User).filter(...))
    if not invitee.is_online:
        raise HTTPException(400, "User not online")

    # More business logic...

# ✅ Correct - delegate to processing layer
@router.post("/conversations")
async def create_conversation(
    data: ConversationCreate,
    conv_service: ConversationService = Depends()
):
    return await handle_create_conversation(data, conv_service)
```

## 🏗️ Architecture: Domain-driven route organization

**HTTP Request → Route Handler → Processing Logic → Service Layer → Response**

Routes are organized by domain with consistent delegation patterns.

## 📋 Domain route organization matrix

| Route File           | Domain                  | Primary Responsibilities               | Main Endpoints        | Dependencies                          |
| -------------------- | ----------------------- | -------------------------------------- | --------------------- | ------------------------------------- |
| **conversations.py** | Conversation management | CRUD, messaging, participant flow      | `/conversations/*`    | ConversationService, processing logic |
| **participants.py**  | Participation workflow  | Invitations, status updates            | `/participants/*`     | ParticipantService                    |
| **users.py**         | User data aggregation   | User listings, profiles                | `/users/*`            | UserService                           |
| **auth_routes.py**   | Authentication API      | Login, register, password reset (JSON) | `/auth/*`             | Authentication logic                  |
| **auth_pages.py**    | Authentication UI       | Login, register forms (HTML)           | `/login`, `/register` | Authentication logic                  |
| **me.py**            | Current user context    | User's conversations, invitations      | `/me/*`               | UserService                           |

## 📁 Directory structure

**Domain route files:**

- `conversations.py` - Conversation CRUD, messaging, and participant management
- `participants.py` - Participant invitation and status management
- `users.py` - User listing and profile access
- `me.py` - Current user's data and actions

**Authentication routes:**

- `auth_routes.py` - JSON API endpoints for authentication
- `auth_pages.py` - HTML forms for authentication

**Package files:**

- `__init__.py` - Route exports and package configuration

## 🔧 Implementation patterns

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

### Delegation to processing logic pattern

Routes delegate all business logic to processing functions:

```python
# Route handles HTTP concerns only
@router.post("/conversations")
async def create_conversation(
    invitee_username: str = Form(...),  # HTTP form parsing
    initial_message: str = Form(...),
    user: User = Depends(current_active_user),  # Authentication
    conv_service: ConversationService = Depends(get_conversation_service),
):
    # Delegate to processing logic
    conversation = await handle_create_conversation(
        invitee_username=invitee_username,
        initial_message=initial_message,
        creator_user=user,
        conv_service=conv_service,
    )

    # HTTP response formatting
    redirect_url = f"/conversations/{conversation.slug}"
    return RedirectResponse(url=redirect_url)
```

### Response formatting patterns

Use APIResponse for consistent response handling:

```python
# HTML responses with templates
@router.get("/conversations")
async def list_conversations(request: Request):
    conversations = await handle_list_conversations()
    return APIResponse.html_response(
        template_name="conversations/list.html",
        context={"conversations": conversations},
        request=request,
    )

# JSON API responses
@router.post("/api/conversations")
async def create_conversation_api(data: ConversationCreate):
    conversation = await handle_create_conversation(data)
    return conversation  # Auto-serialized to JSON

# Redirect responses
@router.post("/conversations")
async def create_conversation_form():
    conversation = await handle_create_conversation()
    return RedirectResponse(
        url=f"/conversations/{conversation.slug}",
        status_code=status.HTTP_303_SEE_OTHER
    )
```

## 🚨 Common issues and solutions

### Issue: Business logic creeping into routes

**Problem**: Routes start containing validation, business rules, or data processing
**Solution**: Move all logic to processing layer, keep routes thin

```python
# ❌ Wrong - business logic in route
@router.post("/conversations")
async def create_conversation(username: str = Form(...)):
    if len(username) < 3:  # Validation logic
        raise HTTPException(400, "Username too short")

    user = await find_user(username)  # Database query
    if not user.is_online:  # Business rule
        raise HTTPException(400, "User offline")

# ✅ Correct - delegate to processing
@router.post("/conversations")
async def create_conversation(username: str = Form(...)):
    return await handle_create_conversation(username=username)
```

### Issue: Inconsistent error handling

**Problem**: Different routes handle errors differently
**Solution**: Use BaseRouter for standardized error handling

```python
# ❌ Wrong - manual error handling in each route
@router.post("/conversations")
async def create_conversation():
    try:
        return await handle_create_conversation()
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, "Internal error")

# ✅ Correct - BaseRouter handles errors automatically
router = BaseRouter(router=APIRouter())

@router.post("/conversations")  # Error handling automatic
async def create_conversation():
    return await handle_create_conversation()
```

### Issue: Mixed form and JSON handling

**Problem**: Routes trying to handle both form data and JSON inconsistently
**Solution**: Separate routes for different content types or use processing logic

```python
# ✅ Approach 1: Separate routes for different formats
@router.post("/conversations")  # Form submission
async def create_conversation_form(
    username: str = Form(...),
    message: str = Form(...)
):
    return await handle_create_conversation(username, message)

@router.post("/api/conversations")  # JSON API
async def create_conversation_api(data: ConversationCreate):
    return await handle_create_conversation(data.username, data.message)

# ✅ Approach 2: Processing logic handles format detection
@router.post("/conversations")
async def create_conversation(request: Request):
    return await handle_create_conversation(request=request)
```

## 📋 Route registration and organization

### Main application route registration

```python
# In main.py
from src.api.routes import (
    conversations,
    participants,
    users,
    auth_routes,
    auth_pages,
    me,
)

app.include_router(conversations.conversations_router_instance, tags=["conversations"])
app.include_router(participants.participants_router_instance, tags=["participants"])
app.include_router(users.users_router_instance, tags=["users"])
app.include_router(auth_routes.auth_api_router_instance, prefix="/auth", tags=["auth-api"])
app.include_router(auth_pages.auth_pages_router_instance, tags=["auth-pages"])
app.include_router(me.me_router_instance, prefix="/me", tags=["me"])
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

## 📚 Related documentation

- ../common/README.md](../common/README.md) - Shared API utilities and BaseRouter
- ../../logic/README.md](../../logic/README.md) - Processing logic that routes delegate to
- ../README.md](../README.md) - Overall API layer architecture
