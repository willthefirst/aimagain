# Services layer: Business logic and transaction coordination

The `services/` directory contains the **business logic layer** of the application, implementing domain-specific operations, transaction management, and coordination between repositories while enforcing business rules and authorization.

## Core philosophy: Domain-driven business logic

Services encapsulate **business rules and workflows**, coordinating multiple repositories within transactions while maintaining clean separation from HTTP concerns and data access details.

### What we do

- **Business rule enforcement**: Validate business constraints before performing operations
- **Transaction coordination**: Orchestrate multiple repository operations within database transactions
- **Authorization logic**: Ensure users can only perform actions they're authorized for
- **Error handling with context**: Convert database/repository errors to domain-specific exceptions

**Example**: A service method with business rules and transaction handling:

```python
class [Entity]Service:
    async def create_[entity](
        self,
        creator_user: User,
        data: [Entity]Create,
    ) -> [Entity]:
        # 1. Business rule validation
        if not self._validate_rules(data, creator_user):
            raise BusinessRuleError("Validation failed.")

        try:
            # 2. Repository operations
            new_entity = await self.[entity]_repo.create(data)
            # 3. Transaction management
            await self.session.commit()
            await self.session.refresh(new_entity)
        except IntegrityError as e:
            await self.session.rollback()
            raise ConflictError("Could not create entity due to a data conflict.")

        return new_entity
```

### What we don't do

- **HTTP handling**: Services never deal with requests, responses, or HTTP status codes
- **Direct database queries**: All data access goes through repository interfaces
- **Template rendering**: UI concerns belong in the API layer
- **Configuration management**: Environment/config logic stays in core layer

**Example**: Don't mix HTTP concerns with business logic:

```python
# Bad - HTTP logic in service
class [Entity]Service:
    async def create_entity(self, request: Request) -> Response:
        data = await request.json()  # HTTP parsing
        entity = await self.repo.create(data)
        return JSONResponse({"entity": entity})  # HTTP response

# Good - pure business logic
class [Entity]Service:
    async def create_entity(
        self, data: [Entity]Create, user: User
    ) -> [Entity]:
        # Business validation and logic only
        return await self.[entity]_repo.create(data)
```

## Architecture: Service provider pattern with dependency injection

**API -> Processing Logic -> Services -> Repositories -> Database**

Services coordinate business operations while repositories handle data access.

## Service responsibility matrix

| Service         | Primary Domain        | Key Responsibilities             | Dependencies |
| --------------- | --------------------- | -------------------------------- | ------------ |
| **UserService** | User data aggregation | Fetch user data, user operations | User repo    |

## Directory structure

**Core service files:**

- `user_service.py` - User-related business logic

**Supporting infrastructure:**

- `dependencies.py` - FastAPI dependency injection setup for all services
- `provider.py` - ServiceProvider singleton pattern for service instantiation
- `exceptions.py` - Domain-specific exception hierarchy
- `__init__.py` - Package initialization

## Implementation patterns

### Creating a new service class

1. **Define the service** in `[domain]_service.py`:

```python
import logging
from uuid import UUID
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.repositories.[domain]_repository import [Domain]Repository
from .exceptions import BusinessRuleError, DatabaseError, ServiceError

logger = logging.getLogger(__name__)

class [Domain]Service:
    def __init__(self, [domain]_repository: [Domain]Repository):
        self.[domain]_repo = [domain]_repository
        self.session = [domain]_repository.session

    async def create_[entity](self, data: [Entity]Create, user: User) -> [Entity]:
        """Business logic with validation, authorization, and transaction handling."""
        # 1. Business rule validation
        if not self._validate_business_rules(data, user):
            raise BusinessRuleError("Validation failed")

        try:
            # 2. Repository operations
            entity = await self.[domain]_repo.create_[entity](data)

            # 3. Transaction management
            await self.session.commit()
            await self.session.refresh(entity)

        except IntegrityError as e:
            await self.session.rollback()
            logger.warning(f"Integrity error: {e}", exc_info=True)
            raise ConflictError("Data conflict occurred")
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f"Database error: {e}", exc_info=True)
            raise DatabaseError("Database operation failed")
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Unexpected error: {e}", exc_info=True)
            raise ServiceError("An unexpected error occurred")

        return entity
```

2. **Add dependency injection** in `dependencies.py`:

```python
def get_[domain]_service(
    [domain]_repo: [Domain]Repository = Depends(get_[domain]_repository),
) -> [Domain]Service:
    """Provides an instance of the [Domain]Service."""
    return ServiceProvider.get_service(
        [Domain]Service,
        [domain]_repository=[domain]_repo,
    )
```

3. **Use in API routes**:

```python
@router.post("/[domain]")
async def create_[entity](
    data: [Entity]Create,
    service: [Domain]Service = Depends(get_[domain]_service),
    user: User = Depends(current_user)
):
    return await service.create_[entity](data, user)
```

### Service dependency injection pattern

Services use the **ServiceProvider singleton pattern** for efficient dependency management:

```python
# Serviceprovider manages singleton instances
class ServiceProvider:
    _instances: Dict[Type[T], T] = {}

    @classmethod
    def get_service(cls, service_class: Type[T], **dependencies: Any) -> T:
        if service_class not in cls._instances:
            cls._instances[service_class] = service_class(**dependencies)
        return cls._instances[service_class]

# Dependency functions provide configured service instances
def get_user_service(
    user_repo: UserRepository = Depends(get_user_repository),
) -> UserService:
    return ServiceProvider.get_service(
        UserService,
        user_repository=user_repo,
    )
```

### Transaction management pattern

All services follow consistent transaction handling:

```python
async def business_operation(self, data) -> Result:
    try:
        # 1. Validation and business rules
        self._validate_business_rules(data)

        # 2. Repository operations (multiple if needed)
        result1 = await self.repo1.operation1(data)
        result2 = await self.repo2.operation2(result1)

        # 3. Commit transaction
        await self.session.commit()

        # 4. Refresh entities if needed
        await self.session.refresh(result2)

        return result2

    except IntegrityError as e:
        await self.session.rollback()
        logger.warning(f"Integrity error: {e}", exc_info=True)
        raise ConflictError("Data conflict occurred")
    except SQLAlchemyError as e:
        await self.session.rollback()
        logger.error(f"Database error: {e}", exc_info=True)
        raise DatabaseError("Database operation failed")
    except Exception as e:
        await self.session.rollback()
        logger.error(f"Unexpected error: {e}", exc_info=True)
        raise ServiceError("An unexpected error occurred")
```

### Exception hierarchy pattern

Services use domain-specific exceptions that map to HTTP status codes:

```python
# Base service exception
class ServiceError(Exception):
    def __init__(self, message="An internal service error occurred.", status_code=500):
        self.message = message
        self.status_code = status_code

# Specific business exceptions
class BusinessRuleError(ServiceError):
    def __init__(self, message="Action violates business rules."):
        super().__init__(message, status_code=400)

class NotAuthorizedError(ServiceError):
    def __init__(self, message="User not authorized for this action."):
        super().__init__(message, status_code=403)

class ConflictError(ServiceError):
    def __init__(self, message="Operation conflicts with existing state."):
        super().__init__(message, status_code=409)
```

## Common issues and solutions

### Issue: Circular service dependencies

**Problem**: Services need each other but create circular imports

**Solution**: Use repository composition instead of service composition:

```python
# Bad - circular service dependencies
class ServiceA:
    def __init__(self, service_b: ServiceB):
        self.service_b = service_b

class ServiceB:
    def __init__(self, service_a: ServiceA):
        self.service_a = service_a

# Good - compose repositories, not services
class ServiceA:
    def __init__(self, repo_a: RepoA, repo_b: RepoB):
        self.repo_a = repo_a
        self.repo_b = repo_b  # Use repositories directly
```

### Issue: Transaction management across service boundaries

**Problem**: Need to coordinate transactions between multiple services

**Solution**: Keep transactions within single service methods:

```python
# Bad - transactions spanning services
async def create_workflow():
    async with transaction():
        result1 = await service_a.create(data)
        await service_b.process(result1.id)

# Good - single service manages entire transaction
class WorkflowService:
    async def create_workflow(self, data):
        try:
            result1 = await self.repo_a.create(data)
            await self.repo_b.process(result1.id)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
```

### Issue: Business logic leaking into repositories

**Problem**: Complex business validation happening in repository methods

**Solution**: Keep repositories simple, business logic in services:

```python
# Bad - business logic in repository
class [Entity]Repository:
    async def create_entity(self, data, user: User):
        if not self._check_permission(user):  # Business rule in repository
            raise BusinessRuleError("Not allowed")

# Good - business logic in service
class [Entity]Service:
    async def create_entity(self, data, user: User):
        if not self._check_permission(user):  # Business rule in service
            raise BusinessRuleError("Not allowed")
        return await self.[entity]_repo.create_entity(data)
```

## Related documentation

- [API Layer](../api/README.md) - How services are consumed by HTTP routes
- [Repository Layer](../repositories/README.md) - Data access patterns used by services
- [Models Layer](../models/README.md) - Domain entities manipulated by services
- [Main Architecture](../README.md) - Overall application architecture and layer relationships
