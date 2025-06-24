# Repositories layer: Data access and database operations

The `repositories/` directory contains the **data access layer** of the Aimagain application, implementing the **repository pattern** to encapsulate database operations, provide clean abstractions over SQLAlchemy queries, and maintain separation between business logic and data persistence.

## 🎯 Core philosophy: Clean data access abstraction

Repositories provide **focused, domain-specific data access** methods that encapsulate complex SQLAlchemy queries while maintaining transaction boundaries and providing type-safe interfaces for the service layer.

### What we do ✅

- **Query encapsulation**: Complex SQLAlchemy queries wrapped in meaningful method names
- **Relationship loading**: Explicit control over eager/lazy loading using `selectinload` and `joinedload`
- **Transaction management**: Coordinate database operations within service-controlled transactions
- **Type safety**: Return proper domain models with full type annotations
- **Domain-specific methods**: Business-relevant query methods like `list_user_conversations()`

**Example**: Repository method with proper relationship loading and business logic:

```python
class ConversationRepository(BaseRepository):
    async def get_conversation_details(self, conversation_id: UUID) -> Conversation | None:
        """Retrieves full conversation details including participants and messages."""
        stmt = (
            select(Conversation)
            .filter(Conversation.id == conversation_id)
            .options(
                selectinload(Conversation.participants).joinedload(Participant.user),
                selectinload(Conversation.messages).joinedload(Message.sender),
            )
        )
        result = await self.session.execute(stmt)
        try:
            return result.scalars().one()
        except Exception:
            return None
```

### What we don't do ❌

- **Business logic**: Repositories only handle data access, no business rule enforcement
- **Transaction control**: Services manage transaction boundaries (commit/rollback)
- **Error handling with business context**: Raw database errors bubble up to services
- **Cross-domain queries**: Each repository focuses on its primary domain entity

**Example**: Don't implement business logic in repositories:

```python
# ❌ Wrong - business logic in repository
class ConversationRepository:
    async def create_conversation_if_allowed(self, creator: User, invitee: User):
        if not invitee.is_online:  # Business rule checking
            raise BusinessError("User not online")
        # ... validation logic

# ✅ Correct - pure data access
class ConversationRepository:
    async def create_new_conversation(
        self, creator_user: User, invitee_user: User, initial_message_content: str
    ) -> Conversation:
        # Only data persistence operations
        new_conversation = Conversation(slug=f"convo-{uuid.uuid4()}", ...)
        self.session.add(new_conversation)
        await self.session.flush()
        return new_conversation
```

## 🏗️ Architecture: Repository pattern with dependency injection

**Services → Repositories → SQLAlchemy → Database**

Each repository manages one primary domain entity with related data access operations.

## 📋 Repository responsibility matrix

| Repository                 | Primary Entity | Key Responsibilities                       | Related Entities       |
| -------------------------- | -------------- | ------------------------------------------ | ---------------------- |
| **ConversationRepository** | Conversation   | CRUD, user conversations, activity updates | Participants, Messages |
| **UserRepository**         | User           | User lookup, online status, authentication | Participants           |
| **ParticipantRepository**  | Participant    | Membership status, invitations, joining    | Users, Conversations   |
| **MessageRepository**      | Message        | Message creation, conversation history     | Users, Conversations   |

## 📁 Directory structure

**Core repository files:**

- `conversation_repository.py` - Conversation data access and relationship management
- `user_repository.py` - User authentication, lookup, and status management
- `participant_repository.py` - Participation status and membership operations
- `message_repository.py` - Message creation and conversation history

**Infrastructure:**

- `base.py` - BaseRepository with common session management
- `dependencies.py` - FastAPI dependency injection for all repositories

## 🔧 Implementation patterns

### Creating a new repository

1. **Define the repository** in `[entity]_repository.py`:

```python
from typing import Sequence
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import [Entity]
from .base import BaseRepository

class [Entity]Repository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_[entity]_by_id(self, [entity]_id: UUID) -> [Entity] | None:
        """Retrieves a [entity] by its ID."""
        stmt = select([Entity]).filter([Entity].id == [entity]_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_[entities](self) -> Sequence[[Entity]]:
        """Lists all [entities] with appropriate ordering."""
        stmt = select([Entity]).order_by([Entity].created_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create_[entity](self, **kwargs) -> [Entity]:
        """Creates a new [entity] with the provided data."""
        new_[entity] = [Entity](**kwargs)
        self.session.add(new_[entity])
        await self.session.flush()
        await self.session.refresh(new_[entity])
        return new_[entity]
```

2. **Add dependency injection** in `dependencies.py`:

```python
def get_[entity]_repository(
    session: AsyncSession = Depends(get_db_session),
) -> [Entity]Repository:
    """Dependency provider for [Entity]Repository."""
    return [Entity]Repository(session)
```

3. **Use in services**:

```python
class [Entity]Service:
    def __init__(self, [entity]_repository: [Entity]Repository):
        self.[entity]_repo = [entity]_repository
        self.session = [entity]_repository.session
```

### Relationship loading patterns

Control eager/lazy loading explicitly for performance:

```python
# Basic query - minimal data
async def get_conversation_by_id(self, conversation_id: UUID) -> Conversation | None:
    stmt = select(Conversation).filter(Conversation.id == conversation_id)
    result = await self.session.execute(stmt)
    return result.scalars().first()

# Detailed query - with relationships
async def get_conversation_details(self, conversation_id: UUID) -> Conversation | None:
    stmt = (
        select(Conversation)
        .filter(Conversation.id == conversation_id)
        .options(
            selectinload(Conversation.participants).joinedload(Participant.user),
            selectinload(Conversation.messages).joinedload(Message.sender),
        )
    )
    result = await self.session.execute(stmt)
    return result.scalars().first()
```

### Session and transaction patterns

Repositories receive sessions from services (transaction boundary control):

```python
class BaseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

# Repository operations don't commit
async def create_conversation(self, **data) -> Conversation:
    conversation = Conversation(**data)
    self.session.add(conversation)
    await self.session.flush()  # Make available in transaction
    return conversation

# Services control commit/rollback
class ConversationService:
    async def create_conversation(self, data):
        try:
            conversation = await self.repo.create_conversation(**data)
            await self.session.commit()  # Service commits
            return conversation
        except Exception:
            await self.session.rollback()  # Service handles errors
            raise
```

## 🚨 Common issues and solutions

### Issue: N+1 query problems

**Problem**: Accessing relationships in loops causes multiple database queries
**Solution**: Use explicit relationship loading in repository methods

```python
# ❌ Wrong - causes N+1 queries
conversations = await repo.list_conversations()
for conv in conversations:
    print(conv.participants)  # Each access hits database

# ✅ Correct - eager load relationships
async def list_conversations(self) -> Sequence[Conversation]:
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.participants))
        .order_by(Conversation.last_activity_at.desc())
    )
    result = await self.session.execute(stmt)
    return result.scalars().all()
```

### Issue: Session lifecycle confusion

**Problem**: Repository methods trying to commit transactions
**Solution**: Let services control transaction boundaries

```python
# ❌ Wrong - repository committing
async def create_user(self, data):
    user = User(**data)
    self.session.add(user)
    await self.session.commit()  # Repository shouldn't commit
    return user

# ✅ Correct - repository only persists
async def create_user(self, data):
    user = User(**data)
    self.session.add(user)
    await self.session.flush()  # Make available in transaction
    return user
```

### Issue: Complex business queries in wrong layer

**Problem**: Business logic mixed with data access
**Solution**: Keep repositories focused on data operations, move business logic to services

```python
# ❌ Wrong - business logic in repository
async def get_conversations_user_can_join(self, user: User):
    if not user.is_online:  # Business rule
        return []
    # Complex business logic mixed with query

# ✅ Correct - simple data access in repository
async def list_conversations(self) -> Sequence[Conversation]:
    stmt = select(Conversation).order_by(Conversation.created_at.desc())
    result = await self.session.execute(stmt)
    return result.scalars().all()

# Business logic in service
class ConversationService:
    async def get_joinable_conversations(self, user: User):
        if not user.is_online:  # Business logic in service
            return []
        return await self.repo.list_conversations()
```

## 📚 Related documentation

- ../models/README.md](../models/README.md) - Database models and relationships
- ../services/README.md](../services/README.md) - Business logic layer that uses repositories
- ../README.md](../README.md) - Overall application architecture
