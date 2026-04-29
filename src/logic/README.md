# Logic: Processing layer between routes and services

The `logic/` directory contains **processing functions** that handle the orchestration of business operations, serving as the coordination layer between API routes and services while managing error handling, validation, and data transformation for specific use cases.

## Core philosophy: Business operation orchestration

Logic modules handle **complex business workflows** that require coordination between multiple services, proper error handling, and data transformation, providing a clean separation between HTTP concerns (routes) and pure business logic (services).

### What we do

- **Operation orchestration**: Coordinate complex workflows involving multiple services
- **Error translation**: Convert service exceptions into appropriate route-level responses
- **Data transformation**: Transform route input into service method parameters
- **Business rule validation**: Apply operation-specific business rules and constraints
- **Logging and monitoring**: Provide detailed logging for business operations

**Example**: User listing orchestration with error handling:

```python
async def handle_list_users(
    user_repo: UserRepository,
    requesting_user: User,
) -> dict:
    """Orchestrate user listing."""
    users_list = await user_repo.list_users(exclude_user=requesting_user)
    return {"users": users_list, "current_user": requesting_user}
```

### What we don't do

- **Direct database access**: Database operations stay in repositories/services
- **HTTP response creation**: Routes handle HTTP-specific response formatting
- **Business rule enforcement**: Core business rules stay in services
- **Authentication/authorization**: Auth logic stays in auth layer

**Example**: Don't put repository or HTTP logic in processing functions:

```python
# Bad - direct database access in logic
async def handle_list_users(session: AsyncSession, user_id: UUID):
    users = await session.execute(select(User).where(User.id != user_id))
    return users.scalars().all()

# Bad - HTTP response creation in logic
async def handle_get_entity(slug: str) -> JSONResponse:
    entity = await service.get_entity(slug)
    return JSONResponse({"entity": entity})

# Good - orchestration with proper separation
async def handle_list_users(
    user_repo: UserRepository,
    requesting_user: User,
):
    """Orchestrate user listing with filtering logic"""
    users_list = await user_repo.list_users(exclude_user=requesting_user)
    return {"users": users_list, "current_user": requesting_user}
```

## Architecture: Orchestration layer between routes and services

**Routes -> Logic -> Services -> Repositories -> Database**

Logic functions coordinate business operations without handling HTTP or database concerns.

### Transactions: logic owns the commit

`get_db_session` (in [`src/db.py`](../db.py)) yields a session and does **not** auto-commit. Repositories deliberately don't commit either — they `flush()` so the result is visible inside the open transaction, but they leave commit/rollback to the caller (see [`../repositories/README.md`](../repositories/README.md)).

In this codebase the *services* layer is mostly empty stubs, so the *logic* layer is the de-facto service layer and is where the commit goes:

```python
async def handle_set_user_activation(user_id, payload, user_repo, requesting_user):
    target = await user_repo.get_user_by_id(user_id)
    ...
    updated = await user_repo.set_user_activation(target, is_active=...)
    await user_repo.session.commit()   # logic commits because there is no service
    return updated
```

When a real service exists for an entity, move the commit there and update the layer matrix in [`../README.md`](../README.md) so the doc matches reality.

## Processing responsibility matrix

| Module                    | Purpose                              | Key Functions                  |
| ------------------------- | ------------------------------------ | ------------------------------ |
| **user_processing.py**    | User operation coordination          | list users with filtering      |
| **post_processing.py**    | Post operation coordination          | list posts, get post detail, create post (server-sets owner_id, writes audit row, commits), update post (owner-or-admin guard, before/after audit snapshot, commits), build create- and edit-form contexts |
| **audit.py**              | Audit-log helper                     | `record_audit(...)` — append-only mutation row per `RESOURCE_GRAMMAR.md:135`; flushes inside the caller's transaction so the audit lands atomically with the mutation. Wired into post handlers; PRs C/D wire users and auth. |
| **auth_processing.py**    | Authentication workflow coordination | user registration processing   |

## Directory structure

```
logic/
├── user_processing.py          # User operation coordination
├── post_processing.py          # Post operation coordination
└── auth_processing.py          # Authentication process coordination
```

## Implementation patterns

### Standard processing function structure

All processing functions follow this pattern for consistency:

```python
import logging
from typing import Dict, Any

from src.models import User
from src.services.[domain]_service import [Domain]Service, ServiceError
from src.repositories.[domain]_repository import [Domain]Repository

logger = logging.getLogger(__name__)

async def handle_some_operation(
    input_param: str,
    user: User,
    service: [Domain]Service,
    repository: [Domain]Repository,
) -> Dict[str, Any]:
    """
    Handle [operation description] orchestration.

    Args:
        input_param: Description of input parameter
        user: The requesting user
        service: Service dependency for business logic
        repository: Repository dependency for data access

    Returns:
        Dictionary containing processed results

    Raises:
        SpecificError: When specific condition occurs
        ServiceError: For generic service-level errors
    """
    logger.debug(f"Processing [operation] for user {user.id}")

    try:
        # Step 1: Validate and transform input
        processed_input = _validate_and_transform_input(input_param)

        # Step 2: Coordinate service operations
        result = await service.perform_operation(processed_input, user)

        # Step 3: Transform for route consumption
        return _transform_for_route(result, user)

    except SpecificError as e:
        logger.info(f"Business rule violation: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error in handle_some_operation: {e}", exc_info=True)
        raise ServiceError("An unexpected error occurred during operation")
```

### Error handling pattern

Consistent error handling across all processing functions:

```python
async def handle_operation_with_error_handling(
    service: [Domain]Service,
) -> Any:
    """Handle operation with comprehensive error management."""
    try:
        return await service.perform_operation()

    except (BusinessRuleError, ConflictError, NotFoundError) as e:
        # Re-raise known business errors for route handling
        logger.info(f"Business error in operation: {e}")
        raise

    except ServiceError as e:
        # Log and re-raise service errors
        logger.error(f"Service error in operation: {e}", exc_info=True)
        raise

    except Exception as e:
        # Convert unexpected errors to service errors
        logger.error(f"Unexpected error in operation: {e}", exc_info=True)
        raise ServiceError("An unexpected error occurred during operation")
```

### Template context preparation pattern

For routes that render templates:

```python
async def handle_template_rendering_operation(
    request: Request,
    user: User,
    service: [Domain]Service,
) -> Dict[str, Any]:
    """Prepare context for template rendering."""

    # Gather all data needed for template
    primary_data = await service.get_primary_data(user)

    # Prepare template context
    context = {
        "request": request,           # Required for FastAPI templates
        "user": user,                 # Current user context
        "primary_data": primary_data, # Main template data
        "metadata": {                 # Additional context
            "page_title": "Operation Page",
            "active_section": "operations",
        }
    }

    return context
```

## Common issues and solutions

### Issue: Logic functions becoming too complex

**Problem**: Processing functions contain too much business logic
**Solution**: Move business rules to services, keep orchestration only

```python
# Bad - business logic in processing function
async def handle_create_entity(creator_user: User, name: str):
    if creator_user.entity_count >= MAX_ENTITIES:
        raise BusinessRuleError("Too many entities")

# Good - delegate business logic to service
async def handle_create_entity(
    creator_user: User,
    name: str,
    service: [Entity]Service,
):
    # Service handles all business rules
    return await service.create_entity(creator_user, name)
```

### Issue: Inconsistent error handling

**Problem**: Different processing functions handle errors differently
**Solution**: Follow standard error handling pattern

```python
# Bad - inconsistent error handling
async def handle_operation_bad():
    try:
        result = await service.do_something()
        return result
    except Exception:
        return None  # Swallowing errors

# Good - consistent error handling
async def handle_operation_good():
    try:
        return await service.do_something()
    except BusinessError as e:
        logger.info(f"Business error: {e}")
        raise  # Re-raise for route handling
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        raise ServiceError("Unexpected error occurred")
```

### Issue: Mixing HTTP concerns with business logic

**Problem**: Processing functions handle HTTP responses or request parsing
**Solution**: Keep HTTP concerns in routes, business orchestration in logic

```python
# Bad - HTTP concerns in logic
async def handle_get_users(request: Request) -> JSONResponse:
    users = await service.get_users()
    return JSONResponse({"users": [user.dict() for user in users]})

# Good - return data for route to handle
async def handle_get_users(user_repo: UserRepository, requesting_user: User):
    users = await user_repo.list_users(exclude_user=requesting_user)
    return {"users": users, "current_user": requesting_user}
```

## Tests

Colocated tests live alongside the logic modules:

- `test_audit.py` — exercises the `record_audit(...)` helper: round-trip via the repo, no commit (handler owns commit), null-actor support.

When adding or changing a processing function, create `src/logic/test_<file>.py` next to it. Most processing functions can be unit-tested directly with mocks or with the in-memory `db_test_session_manager` fixture for the repositories they depend on.

## Related documentation

- [API Routes](../api/routes/README.md) - Route layer that calls processing functions
- [Services Layer](../services/README.md) - Service layer orchestrated by processing functions
- [Repositories Layer](../repositories/README.md) - Repository layer accessed through services
- [API Common](../api/common/README.md) - Common utilities used in processing functions
