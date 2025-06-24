# Schemas: Request/response validation and serialization

The `schemas/` directory contains **Pydantic schemas** that define the structure and validation rules for API requests and responses, providing type safety, automatic serialization, and comprehensive validation for the Aimagain chat application.

## 🎯 Core philosophy: Type-safe API contracts

Schemas serve as **API contracts** that ensure data consistency between clients and the server while providing automatic validation, serialization, and comprehensive error messages for invalid data.

### What we do ✅

- **Request validation**: Validate incoming API data with clear error messages
- **Response serialization**: Convert database models to JSON with proper field selection
- **Type safety**: Provide full type annotations for IDE support and runtime validation
- **Enum definitions**: Define controlled vocabularies for status fields and categories
- **Configuration**: Use Pydantic's ConfigDict for ORM integration and serialization control

**Example**: Complete schema with validation and serialization:

```python
class ParticipantResponse(BaseModel):
    id: UUID
    user_id: UUID
    conversation_id: UUID
    status: ParticipantStatus  # Enum for controlled values
    invited_by_user_id: UUID | None = None
    initial_message_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    joined_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)  # ORM integration
```

### What we don't do ❌

- **Business logic**: Schemas only define structure and basic validation, no business rules
- **Database operations**: Schemas don't interact with databases directly
- **Complex computed fields**: Keep schemas focused on data structure
- **Authentication logic**: Authentication concerns stay in auth layer

**Example**: Don't implement business logic in schemas:

```python
# ❌ Wrong - business logic in schema
class ConversationCreateRequest(BaseModel):
    invitee_user_id: str
    initial_message: str

    def validate_user_can_create(self, current_user):  # Business logic
        if not current_user.is_online:
            raise ValueError("User must be online")

# ✅ Correct - structure and validation only
class ConversationCreateRequest(BaseModel):
    invitee_user_id: str
    initial_message: str

    @field_validator('initial_message')
    def validate_message_length(cls, v):
        if len(v.strip()) == 0:
            raise ValueError('Message cannot be empty')
        return v.strip()
```

## 🏗️ Architecture: Request/response boundary layer

**API Routes → Schema Validation → Service Layer → Schema Serialization → Response**

Schemas act as the data contract layer between HTTP and business logic.

## 📋 Schema organization matrix

| Schema File         | Domain                  | Responsibilities                             | Schema Types                                                     |
| ------------------- | ----------------------- | -------------------------------------------- | ---------------------------------------------------------------- |
| **conversation.py** | Conversation management | Create requests, responses                   | ConversationCreateRequest, ConversationResponse                  |
| **participant.py**  | Participation workflow  | Status enums, invite/update requests         | ParticipantStatus, ParticipantInviteRequest, ParticipantResponse |
| **message.py**      | Message handling        | Message responses                            | MessageResponse                                                  |
| **user.py**         | User data               | User CRUD operations (extends FastAPI Users) | UserRead, UserCreate, UserUpdate                                 |

## 📁 Directory structure

**Domain schema files:**

- `conversation.py` - Conversation creation and response schemas
- `participant.py` - Participation status, invitations, and responses
- `message.py` - Message representation and validation
- `user.py` - User schemas extending FastAPI Users base schemas

## 🔧 Implementation patterns

### Creating request/response schema pairs

Most domains have both request (input) and response (output) schemas:

```python
# Request schema - validates incoming data
class ConversationCreateRequest(BaseModel):
    invitee_user_id: str  # Required field
    initial_message: str  # Required field

    @field_validator('initial_message')
    def validate_message_not_empty(cls, v):
        if not v.strip():
            raise ValueError('Message cannot be empty')
        return v.strip()

# Response schema - serializes outgoing data
class ConversationResponse(BaseModel):
    id: UUID
    created_by_user_id: UUID
    slug: str
    name: str | None = None  # Optional field
    created_at: datetime
    last_activity_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)  # Enable ORM conversion
```

### Enum definitions for controlled values

Use enums for fields with limited, controlled values:

```python
class ParticipantStatus(str, enum.Enum):
    INVITED = "invited"
    JOINED = "joined"
    REJECTED = "rejected"
    LEFT = "left"

class ParticipantResponse(BaseModel):
    status: ParticipantStatus  # Enforces valid status values
    # ... other fields
```

### Orm integration pattern

Use ConfigDict to enable automatic conversion from SQLAlchemy models:

```python
class MessageResponse(BaseModel):
    id: UUID
    content: str
    conversation_id: UUID
    created_by_user_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# Usage in routes - automatic conversion
@router.get("/messages/{message_id}")
async def get_message(message_id: UUID) -> MessageResponse:
    message = await message_repo.get_by_id(message_id)
    return MessageResponse.model_validate(message)  # Auto-converts from ORM
```

### FastAPI users integration pattern

Extend FastAPI Users schemas for authentication:

```python
from fastapi_users import schemas

class UserRead(schemas.BaseUser):
    username: str  # Add custom fields to base user

class UserCreate(schemas.BaseUserCreate):
    username: str  # Add custom fields to registration

class UserUpdate(schemas.BaseUserUpdate):
    username: str  # Add custom fields to updates
```

## 🚨 Common schema issues and solutions

### Issue: Missing validation leading to bad data

**Problem**: Invalid data gets through to business logic
**Solution**: Add comprehensive field validation

```python
# ❌ Wrong - no validation
class ConversationCreateRequest(BaseModel):
    invitee_user_id: str
    initial_message: str

# ✅ Correct - comprehensive validation
class ConversationCreateRequest(BaseModel):
    invitee_user_id: str
    initial_message: str

    @field_validator('invitee_user_id')
    def validate_user_id(cls, v):
        if not v.strip():
            raise ValueError('User ID cannot be empty')
        return v.strip()

    @field_validator('initial_message')
    def validate_message(cls, v):
        v = v.strip()
        if not v:
            raise ValueError('Message cannot be empty')
        if len(v) > 1000:
            raise ValueError('Message too long (max 1000 characters)')
        return v
```

### Issue: Inconsistent ORM conversion

**Problem**: Some schemas work with ORM models, others don't
**Solution**: Consistently use ConfigDict(from_attributes=True)

```python
# ❌ Wrong - missing ORM configuration
class ConversationResponse(BaseModel):
    id: UUID
    slug: str
    # Will fail when converting from SQLAlchemy model

# ✅ Correct - proper ORM integration
class ConversationResponse(BaseModel):
    id: UUID
    slug: str

    model_config = ConfigDict(from_attributes=True)
```

### Issue: Exposing internal fields in responses

**Problem**: Response schemas include fields that shouldn't be public
**Solution**: Explicitly define what fields to include/exclude

```python
# ❌ Wrong - exposing internal fields
class UserResponse(BaseModel):
    id: UUID
    username: str
    email: str
    password_hash: str  # Should not be exposed!
    internal_notes: str  # Should not be exposed!

# ✅ Correct - only expose public fields
class UserResponse(BaseModel):
    id: UUID
    username: str
    email: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

## 📋 Schema naming conventions

### Consistent naming patterns

```python
# Request schemas - data coming IN
[Domain]CreateRequest
[Domain]UpdateRequest
[Domain]InviteRequest

# Response schemas - data going OUT
[Domain]Response
[Domain]ListResponse

# Enums - controlled vocabularies
[Domain]Status
[Domain]Type
[Domain]Category
```

### Example naming consistency

```python
# Conversation domain
ConversationCreateRequest
ConversationResponse

# Participant domain
ParticipantInviteRequest
ParticipantUpdateRequest
ParticipantResponse
ParticipantStatus  # Enum

# Message domain
MessageResponse

# User domain (follows FastAPI users pattern)
UserRead
UserCreate
UserUpdate
```

## 📋 Validation patterns

### Field validators for business constraints

```python
class ConversationCreateRequest(BaseModel):
    invitee_user_id: str
    initial_message: str

    @field_validator('invitee_user_id')
    def validate_user_id_format(cls, v):
        v = v.strip()
        if not v:
            raise ValueError('User ID cannot be empty')
        # Add format validation if needed
        return v

    @field_validator('initial_message')
    def validate_message_content(cls, v):
        v = v.strip()
        if not v:
            raise ValueError('Message cannot be empty')
        if len(v) > 1000:
            raise ValueError('Message cannot exceed 1000 characters')
        return v
```

### Model validators for cross-field validation

```python
class ParticipantUpdateRequest(BaseModel):
    status: ParticipantStatus
    joined_at: datetime | None = None

    @model_validator(mode='after')
    def validate_joined_at_for_joined_status(self):
        if self.status == ParticipantStatus.JOINED and not self.joined_at:
            self.joined_at = datetime.now(timezone.utc)
        elif self.status != ParticipantStatus.JOINED:
            self.joined_at = None
        return self
```

## 📚 Related documentation

- ../api/routes/README.md](../api/routes/README.md) - API routes that use these schemas for validation
- ../models/README.md](../models/README.md) - Database models that schemas serialize
- ../api/README.md](../api/README.md) - Overall API architecture showing schema role
