# Middleware: Cross-cutting request processing

The `middleware/` directory is the home for **ASGI middleware** that implements cross-cutting concerns for the application, processing requests and responses at the HTTP layer. Currently this directory is empty and ready for new middleware as features are added.

## Core philosophy: Non-intrusive cross-cutting concerns

Middleware handles **application-wide concerns** that span multiple routes and domains, operating transparently without breaking the main request/response flow.

### What we do

- **Transparent operation**: Middleware runs without affecting normal application logic
- **Error isolation**: Middleware failures never break the main request flow
- **Session management**: Properly handle database sessions within middleware context

### What we don't do

- **Business logic**: Middleware handles infrastructure concerns, not domain logic
- **Request blocking**: Middleware errors never prevent request completion
- **Data validation**: Request/response validation stays in schemas and routes
- **Authentication**: Authentication logic stays in auth layer

**Example**: Don't implement business logic in middleware:

```python
# Bad - business logic in middleware
class [Entity]Middleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/[entities]"):
            if not await user_has_permission(request):
                return JSONResponse({"error": "Not allowed"}, 403)

# Good - infrastructure concerns only
class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        logger.info(f"{request.method} {request.url.path} -> {response.status_code}")
        return response
```

## Architecture: Request/response pipeline layer

**HTTP Request -> Middleware -> Routes -> Middleware -> HTTP Response**

Middleware wraps the entire request/response cycle for cross-cutting concerns.

## Directory structure

**Middleware files:**

- `__init__.py` - Package exports and configuration

## Implementation patterns

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
async def _do_background_work(self, request: Request):
    """Perform background work that should not break the request."""
    try:
        # Do work here
        pass
    except Exception as e:
        # Never let background work break the main request
        logger.warning(f"Background work failed: {e}")
        # Don't re-raise - middleware failures should be invisible to users
```

## Common middleware issues and solutions

### Issue: Middleware breaking requests

**Problem**: Middleware errors cause request failures
**Solution**: Always catch and log errors, never re-raise

```python
# Bad - middleware error breaks request
async def dispatch(self, request: Request, call_next):
    response = await call_next(request)
    await self._do_something_risky()  # Can raise exception
    return response

# Good - middleware errors are isolated
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
# Bad - creating sessions directly
async def _update_something(self):
    session = get_session()  # Direct session creation

# Good - use session factory pattern
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

## Related documentation

- [API Layer](../api/README.md) - API layer that middleware wraps
- [Services Layer](../services/README.md) - Services used by middleware for business operations
- [Core Layer](../core/README.md) - Configuration and utilities used by middleware
