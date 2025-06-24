# Middleware: Cross-cutting request processing

The `middleware/` directory contains **ASGI middleware** that implements cross-cutting concerns for the Aimagain application, processing requests and responses at the HTTP layer to provide functionality like user presence tracking and activity monitoring.

## 🎯 Core philosophy: Non-intrusive cross-cutting concerns

Middleware handles **application-wide concerns** that span multiple routes and domains, operating transparently without breaking the main request/response flow while providing valuable functionality like presence tracking.

### What we do ✅

- **User presence tracking**: Automatically update user activity timestamps for authenticated requests
- **Transparent operation**: Middleware runs without affecting normal application logic
- **Error isolation**: Middleware failures never break the main request flow
- **Background processing**: Update user state asynchronously without blocking responses
- **Session management**: Properly handle database sessions within middleware context

**Example**: Presence middleware updating user activity transparently:

```python
class PresenceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Process the request first
        response = await call_next(request)

        # Only update presence after successful requests (2xx and 3xx status codes)
        if 200 <= response.status_code < 400:
            await self._update_user_presence(request)  # Non-blocking background update

        return response
```

### What we don't do ❌

- **Business logic**: Middleware handles infrastructure concerns, not domain logic
- **Request blocking**: Middleware errors never prevent request completion
- **Data validation**: Request/response validation stays in schemas and routes
- **Authentication**: Authentication logic stays in auth layer, middleware only tracks activity

**Example**: Don't implement business logic in middleware:

```python
# ❌ Wrong - business logic in middleware
class ConversationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/conversations"):
            # Check if user has permission to create conversations
            if not await user_can_create_conversations(request):
                return JSONResponse({"error": "Not allowed"}, 403)

# ✅ Correct - infrastructure concerns only
class PresenceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if 200 <= response.status_code < 400:
            await self._update_user_presence(request)  # Just track activity
        return response
```

## 🏗️ Architecture: Request/response pipeline layer

**HTTP Request → Middleware → Routes → Middleware → HTTP Response**

Middleware wraps the entire request/response cycle for cross-cutting concerns.

## 📋 Middleware responsibility matrix

| Middleware             | Purpose                | When It Runs                        | What It Does                                   |
| ---------------------- | ---------------------- | ----------------------------------- | ---------------------------------------------- |
| **PresenceMiddleware** | User activity tracking | After successful requests (2xx/3xx) | Update last_active_at, manage is_online status |

## 📁 Directory structure

**Middleware files:**

- `presence.py` - User presence and activity tracking middleware
- `__init__.py` - Package exports and configuration

## 🔧 Implementation patterns

### Creating new middleware

1. **Define the middleware class** extending BaseHTTPMiddleware:

```python
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
import logging

logger = logging.getLogger(__name__)

class CustomMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, custom_config: str):
        super().__init__(app)
        self.custom_config = custom_config

    async def dispatch(self, request: Request, call_next):
        # Pre-request processing (optional)
        logger.info(f"Processing request: {request.url}")

        try:
            # Process the request
            response = await call_next(request)

            # Post-request processing (optional)
            if response.status_code < 400:
                await self._handle_successful_request(request, response)

            return response

        except Exception as e:
            logger.error(f"Request failed: {e}")
            # Let the error propagate - don't swallow it
            raise
```

2. **Register middleware** in main application:

```python
# In main.py
from src.middleware.custom_middleware import CustomMiddleware

app.add_middleware(
    CustomMiddleware,
    custom_config="some_value"
)
```

### Error handling pattern in middleware

Never let middleware errors break the main request:

```python
async def _update_user_presence(self, request: Request):
    """Update user's last_active_at timestamp"""
    try:
        user_id = await self._get_user_id_from_request(request)
        if not user_id:
            return

        await self._do_presence_update(user_id, request)

    except Exception as e:
        # Never let presence updates break the main request
        logger.warning(f"Failed to update user presence: {e}")
        # Don't re-raise - middleware failures should be invisible to users
```

### Session management pattern in middleware

Handle database sessions properly within middleware context:

```python
async def _do_presence_update(self, user_id: str, request: Request):
    """Update presence using the service"""
    try:
        user_uuid = uuid.UUID(user_id)

        # Get the appropriate session factory
        session_factory = self.session_factory

        # Check for dependency overrides (for testing)
        if hasattr(request.app, "dependency_overrides"):
            from src.db import get_db_session
            overridden_factory = request.app.dependency_overrides.get(get_db_session)
            if overridden_factory:
                session_factory = overridden_factory

        # Use session factory to get database session
        async for session in session_factory():
            try:
                from src.repositories.user_repository import UserRepository
                from src.services.presence_service import PresenceService

                user_repo = UserRepository(session)
                presence_service = PresenceService(user_repo)

                await presence_service.update_user_presence(user_uuid)
                break  # Exit the async generator loop

            except Exception as e:
                logger.warning(f"Error updating presence: {e}")
                raise

    except Exception as e:
        logger.warning(f"Failed to update presence: {e}")
        # Don't re-raise - keep middleware transparent
```

## 🚨 Common middleware issues and solutions

### Issue: Middleware breaking requests

**Problem**: Middleware errors cause request failures
**Solution**: Always catch and log errors, never re-raise

```python
# ❌ Wrong - middleware error breaks request
async def dispatch(self, request: Request, call_next):
    response = await call_next(request)
    await self._do_something_risky()  # Can raise exception
    return response

# ✅ Correct - middleware errors are isolated
async def dispatch(self, request: Request, call_next):
    response = await call_next(request)
    try:
        await self._do_something_risky()
    except Exception as e:
        logger.warning(f"Middleware error: {e}")
        # Don't re-raise - keep request flow intact
    return response
```

### Issue: Database session lifecycle problems

**Problem**: Database sessions not properly managed in middleware
**Solution**: Use dependency injection pattern and session factories

```python
# ❌ Wrong - creating sessions directly
async def _update_something(self):
    session = get_session()  # Direct session creation
    # ... use session

# ✅ Correct - use session factory pattern
def __init__(self, app, session_factory):
    super().__init__(app)
    self.session_factory = session_factory

async def _update_something(self):
    async for session in self.session_factory():
        try:
            # ... use session
            break
        except Exception:
            raise
```

## 📚 Related documentation

- ../api/README.md](../api/README.md) - API layer that middleware wraps
- ../services/README.md](../services/README.md) - Services used by middleware for business operations
- ../core/README.md](../core/README.md) - Configuration and utilities used by middleware
