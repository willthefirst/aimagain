# Schemas: Request/response validation and serialization

The `schemas/` directory contains **Pydantic schemas** that define the structure and validation rules for API requests and responses, providing type safety, automatic serialization, and comprehensive validation.

## Core philosophy: Type-safe API contracts

Schemas serve as **API contracts** that ensure data consistency between clients and the server while providing automatic validation, serialization, and comprehensive error messages for invalid data.

### What we do

- **Request validation**: Validate incoming API data with clear error messages
- **Response serialization**: Convert database models to JSON with proper field selection
- **Type safety**: Provide full type annotations for IDE support and runtime validation
- **Configuration**: Use Pydantic's ConfigDict for ORM integration and serialization control

**Example**: Schema with ORM integration:

```python
class UserRead(schemas.BaseUser):
    username: str

    model_config = ConfigDict(from_attributes=True)  # ORM integration
```

### What we don't do

- **Business logic**: Schemas only define structure and basic validation, no business rules
- **Database operations**: Schemas don't interact with databases directly
- **Complex computed fields**: Keep schemas focused on data structure
- **Authentication logic**: Authentication concerns stay in auth layer

**Example**: Don't implement business logic in schemas:

```python
# Bad - business logic in schema
class UserCreateRequest(BaseModel):
    username: str

    def validate_user_can_register(self, existing_users):  # Business logic
        if len(existing_users) >= MAX_USERS:
            raise ValueError("Too many users")

# Good - structure and validation only
class UserCreateRequest(BaseModel):
    username: str

    @field_validator('username')
    def validate_username(cls, v):
        if len(v.strip()) == 0:
            raise ValueError('Username cannot be empty')
        return v.strip()
```

## Architecture: Request/response boundary layer

**API Routes -> Schema Validation -> Service Layer -> Schema Serialization -> Response**

Schemas act as the data contract layer between HTTP and business logic.

## Schema organization matrix

| Schema File | Domain    | Responsibilities                             | Schema Types                                             |
| ----------- | --------- | -------------------------------------------- | -------------------------------------------------------- |
| **user.py** | User data | User CRUD plus activation state-axis subresource (extends FastAPI Users) and audit snapshots | UserRead, UserCreate, UserUpdate, UserActivationUpdate, UserAuditSnapshot, UserActivationAuditSnapshot |
| **post.py** | Posts     | `PostCreate`/`PostUpdate`/`PostRead`/`PostAuditSnapshot` are kind-discriminated unions keyed on the (required) `kind` field. Create/Update variants apply `extra="forbid"`, strip whitespace, validate ZIPs against `^\d{5}$`, type controlled-vocabulary fields as `Literal[*TUPLE]` against the tuples in [`src/models/post_enums.py`](../models/post_enums.py), type the multi-select fields as `DesiredTimesField` / `ServicesField` / `SettingsField` (each a `list[Literal[*TUPLE]]` annotated with a shared `_scalar_to_list` `BeforeValidator` that wraps a 1-element scalar back into a list — htmx's stock `json-enc` collapses a 1-checkbox-checked group to a string on the wire; default `[]` on Create, `None` = leave-unchanged on Update; PA's `services` and `settings` are `RequiredServicesField` and `RequiredSettingsField` — same aliases plus `Field(min_length=1)` so Create/Update reject empty lists while Read/AuditSnapshot stay tolerant of historic rows), and (for partial update) require at least one mutable field. Read and AuditSnapshot variants share a single `_flatten_post_to_dict` helper that reads the per-kind detail relationship and field tuple from `REGISTERED_KINDS` in [`src/models/post_kinds.py`](../models/post_kinds.py) — adding a kind there is what wires the flatten path up. `post_audit_snapshot(post)` validates a SQLAlchemy `Post` against the audit union and returns a JSON-mode dump. | ClientReferral*, ProviderAvailability* variants of Create/Update/Read/AuditSnapshot, plus the discriminated-union aliases PostCreate/PostUpdate/PostRead/PostAuditSnapshot and the helper `post_audit_snapshot` |

## Directory structure

**Domain schema files:**

- `user.py` - User schemas extending FastAPI Users base schemas
- `post.py` - Per-kind post schemas wrapped in discriminated-union aliases (`PostCreate`/`PostUpdate`/`PostRead`/`PostAuditSnapshot`) keyed on the required `kind` field. The Read and AuditSnapshot variants share one `_flatten_post_to_dict` helper that reads from `REGISTERED_KINDS` in [`src/models/post_kinds.py`](../models/post_kinds.py); adding a new kind means a registry entry there plus the four Pydantic variant classes here. Controlled-vocabulary fields use `Literal[*TUPLE]` against the tuples in [`src/models/post_enums.py`](../models/post_enums.py); the `test_schema_literals_match_model_tuples` guardrail in `test_post.py` keeps schema and model in lockstep.

## Implementation patterns

### Creating request/response schema pairs

Most domains have both request (input) and response (output) schemas:

```python
# Request schema - validates incoming data
class [Entity]CreateRequest(BaseModel):
    name: str  # Required field

    @field_validator('name')
    def validate_name_not_empty(cls, v):
        if not v.strip():
            raise ValueError('Name cannot be empty')
        return v.strip()

# Response schema - serializes outgoing data
class [Entity]Response(BaseModel):
    id: UUID
    name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)  # Enable ORM conversion
```

### Orm integration pattern

Use ConfigDict to enable automatic conversion from SQLAlchemy models:

```python
class [Entity]Response(BaseModel):
    id: UUID
    name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# Usage in routes - automatic conversion
@router.get("/[entities]/{entity_id}")
async def get_entity(entity_id: UUID) -> [Entity]Response:
    entity = await repo.get_by_id(entity_id)
    return [Entity]Response.model_validate(entity)  # Auto-converts from ORM
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

## Common schema issues and solutions

### Issue: Missing validation leading to bad data

**Problem**: Invalid data gets through to business logic
**Solution**: Add comprehensive field validation

```python
# Bad - no validation
class [Entity]CreateRequest(BaseModel):
    name: str

# Good - comprehensive validation
class [Entity]CreateRequest(BaseModel):
    name: str

    @field_validator('name')
    def validate_name(cls, v):
        v = v.strip()
        if not v:
            raise ValueError('Name cannot be empty')
        if len(v) > 200:
            raise ValueError('Name too long (max 200 characters)')
        return v
```

### Issue: Inconsistent ORM conversion

**Problem**: Some schemas work with ORM models, others don't
**Solution**: Consistently use ConfigDict(from_attributes=True)

```python
# Bad - missing ORM configuration
class [Entity]Response(BaseModel):
    id: UUID
    name: str
    # Will fail when converting from SQLAlchemy model

# Good - proper ORM integration
class [Entity]Response(BaseModel):
    id: UUID
    name: str

    model_config = ConfigDict(from_attributes=True)
```

### Issue: Exposing internal fields in responses

**Problem**: Response schemas include fields that shouldn't be public
**Solution**: Explicitly define what fields to include/exclude

```python
# Bad - exposing internal fields
class UserResponse(BaseModel):
    id: UUID
    username: str
    email: str
    password_hash: str  # Should not be exposed!

# Good - only expose public fields
class UserResponse(BaseModel):
    id: UUID
    username: str
    email: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

## Schema naming conventions

### Consistent naming patterns

```python
# Request schemas - data coming IN
[Domain]CreateRequest
[Domain]UpdateRequest

# Response schemas - data going OUT
[Domain]Response
[Domain]ListResponse

# Enums - controlled vocabularies
[Domain]Status
[Domain]Type
```

### Example naming consistency

```python
# User domain (follows FastAPI users pattern)
UserRead
UserCreate
UserUpdate

# New domain example
[Entity]CreateRequest
[Entity]Response
[Entity]Status  # Enum
```

## Tests

Colocated tests live alongside the schema modules:

- `test_post.py` — exercises the kind-discriminated `PostCreate`/`PostUpdate` unions: explicit-kind variants, the `extra="forbid"` boundary (rejects `owner_id`, unknown fields, cross-kind field bleed), per-kind whitespace stripping, ZIP regex, controlled-vocabulary rejection, and the partial-update at-least-one-field rule. Also covers `post_audit_snapshot` flattening through the right detail relationship for each registered kind, and the `test_schema_literals_match_model_tuples` guardrail that asserts the `Literal[*TUPLE]` types here stay aligned with the source-of-truth tuples in `src/models/post_enums.py`.

Add `src/schemas/test_<schema_name>.py` when a schema has non-trivial validators or computed fields whose behavior isn't obvious from the field definitions.

## Related documentation

- [API Routes](../api/routes/README.md) - API routes that use these schemas for validation
- [Models Layer](../models/README.md) - Database models that schemas serialize
- [API Layer](../api/README.md) - Overall API architecture showing schema role
