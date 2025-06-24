# Logic: Processing layer between routes and services

The `logic/` directory contains **processing functions** that handle the orchestration of business operations, serving as the coordination layer between API routes and services while managing error handling, validation, and data transformation for specific use cases.

## 🎯 Core philosophy: Business operation orchestration

Logic modules handle **complex business workflows** that require coordination between multiple services, proper error handling, and data transformation, providing a clean separation between HTTP concerns (routes) and pure business logic (services).

### What we do ✅

- **Operation orchestration**: Coordinate complex workflows involving multiple services
- **Error translation**: Convert service exceptions into appropriate route-level responses
- **Data transformation**: Transform route input into service method parameters
- **Business rule validation**: Apply operation-specific business rules and constraints
- **Logging and monitoring**: Provide detailed logging for business operations

**Example**: Conversation creation orchestration with error handling:

```python
async def handle_create_conversation(
    invitee_username: str,
    initial_message: str,
    creator_user: User,
    conv_service: ConversationService,
    user_repo: UserRepository,
) -> Conversation:
    """Orchestrates conversation creation with proper error handling"""

    # Step 1: Resolve invitee by username
    invitee_user = await user_repo.get_user_by_username(invitee_username)
    if not invitee_user:
        raise ServiceUserNotFoundError(f"User with username '{invitee_username}' not found.")

    # Step 2: Create conversation through service
    new_conversation = await conv_service.create_new_conversation(
        creator_user=creator_user,
        invitee_user_id=invitee_user.id,
        initial_message_content=initial_message,
    )

    return new_conversation
```

### What we don't do ❌

- **Direct database access**: Database operations stay in repositories/services
- **HTTP response creation**: Routes handle HTTP-specific response formatting
- **Business rule enforcement**: Core business rules stay in services
- **Authentication/authorization**: Auth logic stays in auth layer

**Example**: Don't put repository or HTTP logic in processing functions:

```python
# ❌ Wrong - direct database access in logic
async def handle_list_users(session: AsyncSession, user_id: UUID):
    users = await session.execute(select(User).where(User.id != user_id))
    return users.scalars().all()

# ❌ Wrong - HTTP response creation in logic
async def handle_get_conversation(slug: str) -> JSONResponse:
    conversation = await service.get_conversation(slug)
    return JSONResponse({"conversation": conversation})

# ✅ Correct - orchestration with proper separation
async def handle_list_users(
    user_repo: UserRepository,
    requesting_user: User,
    participated_with_filter: str | None = None,
):
    """Orchestrate user listing with filtering logic"""
    filter_user = requesting_user if participated_with_filter == "me" else None

    users_list = await user_repo.list_users(
        exclude_user=requesting_user,
        participated_with_user=filter_user,
    )

    return {"users": users_list, "current_user": requesting_user}
```

## 🏗️ Architecture: Orchestration layer between routes and services

**Routes → Logic → Services → Repositories → Database**

Logic functions coordinate business operations without handling HTTP or database concerns.

## 📋 Processing responsibility matrix

| Module                         | Purpose                              | Key Functions                                |
| ------------------------------ | ------------------------------------ | -------------------------------------------- |
| **conversation_processing.py** | Conversation workflow orchestration  | create, get details, list, invite, messaging |
| **user_processing.py**         | User operation coordination          | list users with filtering                    |
| **participant_processing.py**  | Participant workflow management      | invitation handling, participant operations  |
| **auth_processing.py**         | Authentication workflow coordination | user registration processing                 |
| **me_processing.py**           | User profile and personal data       | personal conversation/invitation management  |

## 📁 Directory structure

```
logic/
├── conversation_processing.py  # Conversation workflow orchestration
├── user_processing.py          # User operation coordination
├── participant_processing.py   # Participant management workflows
├── auth_processing.py          # Authentication process coordination
└── me_processing.py            # Personal/profile operation processing
```

## 🔧 Implementation patterns

### Standard processing function structure

All processing functions follow this pattern for consistency:

```python
import logging
from typing import Dict, Any

from src.models import User
from src.services.some_service import SomeService, ServiceError
from src.repositories.some_repository import SomeRepository

logger = logging.getLogger(__name__)

async def handle_some_operation(
    input_param: str,
    user: User,
    service: SomeService,
    repository: SomeRepository,
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
    service: SomeService,
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

### Multi-service orchestration pattern

When coordinating multiple services:

```python
async def handle_complex_workflow(
    user: User,
    primary_service: PrimaryService,
    secondary_service: SecondaryService,
    repository: SomeRepository,
) -> Dict[str, Any]:
    """Orchestrate workflow involving multiple services."""

    # Step 1: Validate with repository
    entity = await repository.get_entity_by_criteria(user.id)
    if not entity:
        raise NotFoundError("Required entity not found")

    # Step 2: Primary service operation
    primary_result = await primary_service.perform_primary_operation(entity, user)

    # Step 3: Secondary service operation (dependent on primary)
    try:
        secondary_result = await secondary_service.perform_secondary_operation(
            primary_result.id, user
        )
    except SecondaryServiceError:
        # Handle partial failure - may need rollback
        logger.warning("Secondary operation failed, continuing with primary result")
        secondary_result = None

    # Step 4: Combine results for route
    return {
        "primary": primary_result,
        "secondary": secondary_result,
        "user": user,
    }
```

### Template context preparation pattern

For routes that render templates:

```python
async def handle_template_rendering_operation(
    request: Request,
    user: User,
    service: SomeService,
) -> Dict[str, Any]:
    """Prepare context for template rendering."""

    # Gather all data needed for template
    primary_data = await service.get_primary_data(user)
    secondary_data = await service.get_secondary_data(user)

    # Prepare template context
    context = {
        "request": request,           # Required for FastAPI templates
        "user": user,                 # Current user context
        "primary_data": primary_data, # Main template data
        "secondary_data": secondary_data, # Supporting data
        "metadata": {                 # Additional context
            "page_title": "Operation Page",
            "active_section": "operations",
        }
    }

    return context
```

## 🚨 Common issues and solutions

### Issue: Logic functions becoming too complex

**Problem**: Processing functions contain too much business logic
**Solution**: Move business rules to services, keep orchestration only

```python
# ❌ Wrong - business logic in processing function
async def handle_create_conversation(creator_user: User, invitee_username: str):
    # Don't implement business rules here
    if creator_user.conversation_count >= MAX_CONVERSATIONS:
        raise BusinessRuleError("Too many conversations")

    if invitee_username == creator_user.username:
        raise BusinessRuleError("Cannot invite yourself")

# ✅ Correct - delegate business logic to service
async def handle_create_conversation(
    creator_user: User,
    invitee_username: str,
    conv_service: ConversationService,
):
    # Service handles all business rules
    return await conv_service.create_conversation(creator_user, invitee_username)
```

### Issue: Inconsistent error handling

**Problem**: Different processing functions handle errors differently
**Solution**: Follow standard error handling pattern

```python
# ❌ Wrong - inconsistent error handling
async def handle_operation_bad():
    try:
        result = await service.do_something()
        return result
    except Exception:
        return None  # Swallowing errors

# ✅ Correct - consistent error handling
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
# ❌ Wrong - HTTP concerns in logic
async def handle_get_users(request: Request) -> JSONResponse:
    users = await service.get_users()
    return JSONResponse({"users": [user.dict() for user in users]})

# ✅ Correct - return data for route to handle
async def handle_get_users(user_repo: UserRepository, requesting_user: User):
    users = await user_repo.list_users(exclude_user=requesting_user)
    return {"users": users, "current_user": requesting_user}
```

## 📚 Related documentation

- [../api/routes/README.md](../api/routes/README.md) - Route layer that calls processing functions
- [../services/README.md](../services/README.md) - Service layer orchestrated by processing functions
- [../repositories/README.md](../repositories/README.md) - Repository layer accessed through services
- [../api/common/README.md](../api/common/README.md) - Common utilities used in processing functions
