# Models layer: Database schema and domain entities

The `models/` directory contains **SQLAlchemy data models** that define the database schema, relationships, and constraints for the Aimagain chat application, implementing a **relational domain model** with clear entity boundaries and relationships.

## �� Core philosophy: Domain-driven data modeling

Models represent **business entities** with clear relationships, enforcing data integrity through database constraints while supporting the application's conversation-centric domain.

### What we do ✅

- **Domain entity modeling**: Each model represents a clear business concept (User, Conversation, Message, Participant)
- **Relationship management**: Explicit foreign keys and SQLAlchemy relationships for data integrity
- **Audit trail support**: Automatic timestamps (created_at, updated_at) and soft deletion (deleted_at)
- **UUID primary keys**: Secure, non-guessable identifiers for all entities
- **Database constraint enforcement**: Unique constraints and foreign key relationships

**Example**: Complete model with relationships and constraints:

```python
class Participant(BaseModel):
    __tablename__ = "participants"

    # Foreign key relationships
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    conversation_id = Column(Uuid(as_uuid=True), ForeignKey("conversations.id"), nullable=False)

    # Enum for controlled status values
    status = Column(SQLAlchemyEnum(ParticipantStatus), nullable=False)

    # Optional foreign keys for business logic
    invited_by_user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
    initial_message_id = Column(Uuid(as_uuid=True), ForeignKey("messages.id"), nullable=True)

    # Business-specific timestamps
    joined_at = Column(DateTime(timezone=True), nullable=True)

    # SQLAlchemy relationships
    user = relationship("User", back_populates="participations", foreign_keys=[user_id])
    conversation = relationship("Conversation", back_populates="participants", foreign_keys=[conversation_id])

    # Database constraint
    __table_args__ = (
        UniqueConstraint("user_id", "conversation_id", name="uq_participant_user_conversation"),
    )
```

### What we don't do ❌

- **Business logic in models**: Models only contain data structure and relationships, no business rules
- **Computed properties with side effects**: Properties should be simple data access, not complex calculations
- **Direct API serialization**: Models are not directly returned to APIs (use schemas for that)
- **Complex validation logic**: Database constraints for data integrity, business validation in services

**Example**: Keep models focused on data structure:

```python
# ❌ Wrong - business logic in model
class Conversation(BaseModel):
    def can_user_join(self, user: User) -> bool:  # Business logic
        if not user.is_online:
            return False
        # ... more business logic

    def send_message(self, content: str, user: User):  # Service operation
        # ... complex business operation

# ✅ Correct - data structure only
class Conversation(BaseModel):
    __tablename__ = "conversations"

    name = Column(Text, nullable=True)
    slug = Column(Text, unique=True, nullable=False)
    created_by_user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    last_activity_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships for data access
    creator = relationship("User", back_populates="created_conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
```

## 🏗️ Architecture: Relational domain model

**Models → Relationships → Database Schema**

Each model maps to a database table with explicit relationships managed by SQLAlchemy.

## 📋 Domain entity matrix

| Model          | Primary Purpose               | Key Relationships                    | Unique Constraints              |
| -------------- | ----------------------------- | ------------------------------------ | ------------------------------- |
| **User**       | Authentication and identity   | Created conversations, messages, participations | username, email                 |
| **Conversation** | Chat room/thread container   | Creator, participants, messages      | slug                            |
| **Message**    | Individual chat messages      | Sender, conversation, initial invitations | none                            |
| **Participant** | User membership in conversations | User, conversation, inviter        | (user_id, conversation_id)      |

## 📁 Directory structure

**Core model files:**

- `user.py` - User authentication and profile (extends FastAPI Users)
- `conversation.py` - Chat conversation/room definition
- `message.py` - Individual chat messages
- `participant.py` - User participation in conversations with status tracking

**Infrastructure:**

- `base.py` - BaseModel with common fields (id, timestamps, soft deletion)
- `__init__.py` - Model exports and package configuration

## 🔧 Implementation patterns

### Creating a new model

1. **Define the model** in `[entity].py`:

```python
from sqlalchemy import Column, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid
from .base import BaseModel

class NewEntity(BaseModel):
    __tablename__ = "new_entities"

    # Business fields
    name = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)

    # Foreign key relationships
    owner_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # SQLAlchemy relationships
    owner = relationship("User", back_populates="owned_entities")

    # Database constraints
    __table_args__ = (
        UniqueConstraint("name", "owner_id", name="uq_entity_name_per_owner"),
    )
```

2. **Add to model exports** in `__init__.py`:

```python
from .new_entity import NewEntity

__all__ = [
    "BaseModel",
    "metadata",
    "User",
    "Conversation",
    "Message",
    "Participant",
    "NewEntity",  # Add new model
]
```

3. **Create migration** using Alembic:

```bash
alembic revision --autogenerate -m "Add new_entity table"
alembic upgrade head
```

### Basemodel inheritance pattern

All models inherit from `BaseModel` for consistent structure:

```python
class BaseModel(declarative_base()):
    __abstract__ = True

    # UUID primary key
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Automatic audit timestamps
    @declared_attr
    def created_at(cls):
        return Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    @declared_attr
    def updated_at(cls):
        return Column(DateTime(timezone=True), nullable=False,
                     server_default=func.now(), onupdate=func.now())

    # Soft deletion support
    @declared_attr
    def deleted_at(cls):
        return Column(DateTime(timezone=True), nullable=True)
```

### Relationship definition pattern

Use explicit foreign_keys and back_populates for clarity:

```python
class User(BaseModel):
    # One-to-many: User creates many conversations
    created_conversations = relationship(
        "Conversation",
        back_populates="creator",
        foreign_keys="Conversation.created_by_user_id"
    )

    # One-to-many: User has many participations
    participations = relationship(
        "Participant",
        back_populates="user",
        foreign_keys="Participant.user_id"
    )

class Conversation(BaseModel):
    created_by_user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # Many-to-one: Conversation belongs to one creator
    creator = relationship(
        "User",
        back_populates="created_conversations",
        foreign_keys=[created_by_user_id]
    )

    # One-to-many: Conversation has many participants
    participants = relationship(
        "Participant",
        back_populates="conversation",
        cascade="all, delete-orphan"
    )
```

### Database constraint patterns

Use SQLAlchemy constraints for data integrity:

```python
class Participant(BaseModel):
    # Ensure one participant record per user per conversation
    __table_args__ = (
        UniqueConstraint(
            "user_id", "conversation_id",
            name="uq_participant_user_conversation"
        ),
    )

class Conversation(BaseModel):
    # Ensure unique conversation slugs
    slug = Column(Text, unique=True, nullable=False)

class User(BaseModel):
    # Ensure unique usernames
    username = Column(Text, unique=True, nullable=False)
```

## 🚨 Common issues and solutions

### Issue: Circular import dependencies

**Problem**: Models importing each other for type hints causes circular imports

**Solution**: Use string references in relationships and type annotations:

```python
# ❌ Wrong - direct imports cause circular dependencies
from .user import User
from .conversation import Conversation

class Participant(BaseModel):
    user: User = relationship("User", ...)  # Import required

# ✅ Correct - string references avoid imports
class Participant(BaseModel):
    user = relationship("User", back_populates="participations")  # String reference
    conversation = relationship("Conversation", back_populates="participants")
```

### Issue: Missing cascade deletes

**Problem**: Deleting parent records leaves orphaned child records

**Solution**: Use appropriate cascade options on relationships:

```python
# ❌ Wrong - no cascade, orphaned records remain
class Conversation(BaseModel):
    messages = relationship("Message", back_populates="conversation")

# ✅ Correct - cascade deletes child records
class Conversation(BaseModel):
    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan"  # Delete messages when conversation deleted
    )
    participants = relationship(
        "Participant",
        back_populates="conversation",
        cascade="all, delete-orphan"  # Delete participations when conversation deleted
    )
```

### Issue: Missing database constraints

**Problem**: Data integrity issues because constraints only enforced in application code

**Solution**: Add database-level constraints:

```python
# ❌ Wrong - only application validation
class Participant(BaseModel):
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"))
    conversation_id = Column(Uuid(as_uuid=True), ForeignKey("conversations.id"))
    # No database constraint preventing duplicate participation

# ✅ Correct - database constraint prevents duplicates
class Participant(BaseModel):
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    conversation_id = Column(Uuid(as_uuid=True), ForeignKey("conversations.id"), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "conversation_id",
            name="uq_participant_user_conversation"
        ),
    )
```

### Issue: Timezone-naive datetime fields

**Problem**: Datetime fields without timezone information cause comparison issues

**Solution**: Always use timezone-aware datetime columns:

```python
# ❌ Wrong - timezone-naive datetime
class Message(BaseModel):
    sent_at = Column(DateTime, nullable=False)  # No timezone

# ✅ Correct - timezone-aware datetime
class Message(BaseModel):
    sent_at = Column(DateTime(timezone=True), nullable=False)  # With timezone
```

## 📚 Related documentation

- [Repository Layer](mdc:../repositories/README.md) - Data access patterns that work with these models
- [Services Layer](mdc:../services/README.md) - Business logic that operates on these domain entities
- [Schemas Layer](mdc:../schemas/README.md) - Request/response validation for these models
- [Main Architecture](mdc:../README.md) - How models fit into the overall application architecture
