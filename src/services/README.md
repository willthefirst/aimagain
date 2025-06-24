# Services layer: Business logic and transaction coordination

The `services/` directory contains the **business logic layer** of the Aimagain application, implementing domain-specific operations, transaction management, and coordination between repositories while enforcing business rules and authorization.

## 🎯 Core philosophy: Domain-driven business logic

Services encapsulate **business rules and workflows**, coordinating multiple repositories within transactions while maintaining clean separation from HTTP concerns and data access details.

### What we do ✅

- **Business rule enforcement**: Validate business constraints like "users must be online to be invited"
- **Transaction coordination**: Orchestrate multiple repository operations within database transactions
- **Authorization logic**: Ensure users can only perform actions they're authorized for
- **Error handling with context**: Convert database/repository errors to domain-specific exceptions
- **Cross-domain operations**: Coordinate between multiple entities (conversations, participants, messages)

**Example**: Creating a conversation with business rules and transaction handling:

```python
class ConversationService:
    async def create_new_conversation(
        self,
        creator_user: User,
        invitee_user_id: UUID,
        initial_message_content: str,
    ) -> Conversation:
        # 1. Business rule validation
        invitee_user = await self.user_repo.get_user_by_id(invitee_user_id)
        if not invitee_user:
            raise UserNotFoundError(f"Invitee user with ID '{invitee_user_id}' not found.")
        if not invitee_user.is_online:
            raise BusinessRuleError("Invitee user is not online.")
        if creator_user.id == invitee_user.id:
            raise BusinessRuleError("Cannot create a conversation with yourself.")

        try:
            # 2. Coordinated repository operations
            new_conversation = await self.conv_repo.create_new_conversation(
                creator_user=creator_user,
                invitee_user=invitee_user,
                initial_message_content=initial_message_content,
            )
            # 3. Transaction management
            await self.session.commit()
            await self.session.refresh(new_conversation)
        except IntegrityError as e:
            await self.session.rollback()
            raise ConflictError("Could not create conversation due to a data conflict.")

        return new_conversation
```

### What we don't do ❌

- **HTTP handling**: Services never deal with requests, responses, or HTTP status codes
- **Direct database queries**: All data access goes through repository interfaces
- **Template rendering**: UI concerns belong in the API layer
- **Configuration management**: Environment/config logic stays in core layer

**Example**: Don't mix HTTP concerns with business logic:

```python
# ❌ Wrong - HTTP logic in service
class ConversationService:
    async def create_conversation(self, request: Request) -> Response:
        data = await request.json()  # HTTP parsing
        conversation = await self.repo.create(data)
        return JSONResponse({"conversation": conversation})  # HTTP response

# ✅ Correct - pure business logic
class ConversationService:
    async def create_new_conversation(
        self, creator_user: User, invitee_user_id: UUID, initial_message: str
    ) -> Conversation:
        # Business validation and logic only
        return await self.conv_repo.create_new_conversation(...)
```

## 🏗️ Architecture: Service provider pattern with dependency injection

**API → Processing Logic → Services → Repositories → Database**

Services coordinate business operations while repositories handle data access.

## 📋 Service responsibility matrix

| Service                 | Primary Domain          | Key Responsibilities                       | Dependencies                |
| ----------------------- | ----------------------- | ------------------------------------------ | --------------------------- |
| **ConversationService** | Conversation management | Create, invite, message coordination       | Conv, Part, Msg, User repos |
| **ParticipantService**  | Participation workflow  | Status updates, invitation handling        | Part, Conv repos            |
| **UserService**         | User data aggregation   | Fetch user conversations and invitations   | Part, Conv repos            |
| **PresenceService**     | User presence tracking  | Update activity timestamps, online status  | User repo                   |
| **MigrationService**    | Data migration          | Handle data transformations and migrations | Multiple repos              |

## 📁 Directory structure

**Core service files:**

- `conversation_service.py` - Complete conversation lifecycle management
- `participant_service.py` - Participant status and invitation workflows
- `user_service.py` - User-centric data aggregation
- `presence_service.py` - User activity and presence tracking
- `migration_service.py` - Data migration and transformation utilities

**Supporting infrastructure:**

- `dependencies.py` - FastAPI dependency injection setup for all services
- `provider.py` - ServiceProvider singleton pattern for service instantiation
- `exceptions.py` - Domain-specific exception hierarchy
- `__init__.py` - Package initialization

## 🔧 Implementation patterns

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
    # ... other repository dependencies
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
def get_conversation_service(
    conv_repo: ConversationRepository = Depends(get_conversation_repository),
    part_repo: ParticipantRepository = Depends(get_participant_repository),
    msg_repo: MessageRepository = Depends(get_message_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> ConversationService:
    return ServiceProvider.get_service(
        ConversationService,
        conversation_repository=conv_repo,
        participant_repository=part_repo,
        message_repository=msg_repo,
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

## 🚨 Common issues and solutions

### Issue: Circular service dependencies

**Problem**: Services need each other but create circular imports

**Solution**: Use repository composition instead of service composition:

```python
# ❌ Wrong - circular service dependencies
class ConversationService:
    def __init__(self, participant_service: ParticipantService):
        self.participant_service = participant_service

class ParticipantService:
    def __init__(self, conversation_service: ConversationService):
        self.conversation_service = conversation_service

# ✅ Correct - compose repositories, not services
class ConversationService:
    def __init__(self, conv_repo: ConversationRepository, part_repo: ParticipantRepository):
        self.conv_repo = conv_repo
        self.part_repo = part_repo  # Use repositories directly

class ParticipantService:
    def __init__(self, part_repo: ParticipantRepository, conv_repo: ConversationRepository):
        self.part_repo = part_repo
        self.conv_repo = conv_repo  # Same repositories, different service focus
```

### Issue: Transaction management across service boundaries

**Problem**: Need to coordinate transactions between multiple services

**Solution**: Keep transactions within single service methods:

```python
# ❌ Wrong - transactions spanning services
async def create_conversation_workflow():
    async with transaction():
        conv = await conversation_service.create_conversation(data)
        await participant_service.add_participant(conv.id, user_id)

# ✅ Correct - single service manages entire transaction
class ConversationService:
    async def create_new_conversation(self, creator: User, invitee_id: UUID, message: str):
        try:
            # All operations in one transaction
            conv = await self.conv_repo.create_conversation(creator, message)
            await self.part_repo.create_participant(creator.id, conv.id, "joined")
            await self.part_repo.create_participant(invitee_id, conv.id, "invited")
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
```

### Issue: Business logic leaking into repositories

**Problem**: Complex business validation happening in repository methods

**Solution**: Keep repositories simple, business logic in services:

```python
# ❌ Wrong - business logic in repository
class ConversationRepository:
    async def create_conversation(self, creator: User, invitee: User, message: str):
        if not invitee.is_online:  # Business rule in repository
            raise BusinessRuleError("Invitee must be online")
        # ... create logic

# ✅ Correct - business logic in service
class ConversationService:
    async def create_new_conversation(self, creator: User, invitee_id: UUID, message: str):
        invitee = await self.user_repo.get_user_by_id(invitee_id)
        if not invitee.is_online:  # Business rule in service
            raise BusinessRuleError("Invitee user is not online")

        return await self.conv_repo.create_conversation(creator, invitee, message)
```

## 📚 Related documentation

- [API Layer](mdc:../api/README.md) - How services are consumed by HTTP routes
- [Repository Layer](mdc:../repositories/README.md) - Data access patterns used by services
- [Models Layer](mdc:../models/README.md) - Domain entities manipulated by services
- [Main Architecture](mdc:../README.md) - Overall application architecture and layer relationships
