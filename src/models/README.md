# Models layer: Database schema and domain entities

The `models/` directory contains **SQLAlchemy data models** that define the database schema and constraints for the application, implementing a **relational domain model** with clear entity boundaries.

## Core philosophy: Domain-driven data modeling

Models represent **business entities** with clear relationships, enforcing data integrity through database constraints.

### What we do

- **Domain entity modeling**: Each model represents a clear business concept (currently just User)
- **Audit trail support**: Automatic timestamps (created_at, updated_at) and soft deletion (deleted_at)
- **UUID primary keys**: Secure, non-guessable identifiers for all entities
- **Database constraint enforcement**: Unique constraints and foreign key relationships

**Example**: A model with constraints:

```python
class User(BaseModel):
    __tablename__ = "users"

    username = Column(Text, unique=True, nullable=False)
```

### What we don't do

- **Business logic in models**: Models only contain data structure and relationships, no business rules
- **Computed properties with side effects**: Properties should be simple data access, not complex calculations
- **Direct API serialization**: Models are not directly returned to APIs (use schemas for that)
- **Complex validation logic**: Database constraints for data integrity, business validation in services

**Example**: Keep models focused on data structure:

```python
# Bad - business logic in model
class User(BaseModel):
    def can_perform_action(self, action: str) -> bool:  # Business logic
        # ... complex business logic

# Good - data structure only
class User(BaseModel):
    __tablename__ = "users"
    username = Column(Text, unique=True, nullable=False)
```

## Architecture: Relational domain model

**Models -> Relationships -> Database Schema**

Each model maps to a database table with explicit relationships managed by SQLAlchemy.

## Domain entity matrix

| Model    | Primary Purpose             | Key Fields | Unique Constraints |
| -------- | --------------------------- | ---------- | ------------------ |
| **User** | Authentication and identity | username   | username, email    |

## Directory structure

**Core model files:**

- `user.py` - User authentication and profile (extends FastAPI Users)

**Infrastructure:**

- `base.py` - BaseModel with common fields (id, timestamps, soft deletion)
- `__init__.py` - Model exports and package configuration

## Implementation patterns

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

When adding relationships between models, use explicit foreign_keys and back_populates for clarity:

```python
class User(BaseModel):
    # One-to-many: User owns many entities
    owned_entities = relationship(
        "NewEntity",
        back_populates="owner",
        foreign_keys="NewEntity.owner_id"
    )

class NewEntity(BaseModel):
    owner_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # Many-to-one: Entity belongs to one owner
    owner = relationship(
        "User",
        back_populates="owned_entities",
        foreign_keys=[owner_id]
    )
```

### Database constraint patterns

Use SQLAlchemy constraints for data integrity:

```python
class NewEntity(BaseModel):
    # Ensure unique name per owner
    __table_args__ = (
        UniqueConstraint(
            "name", "owner_id",
            name="uq_entity_name_per_owner"
        ),
    )

class User(BaseModel):
    # Ensure unique usernames
    username = Column(Text, unique=True, nullable=False)
```

## Common issues and solutions

### Issue: Circular import dependencies

**Problem**: Models importing each other for type hints causes circular imports

**Solution**: Use string references in relationships and type annotations:

```python
# Bad - direct imports cause circular dependencies
from .user import User

class NewEntity(BaseModel):
    user: User = relationship("User", ...)  # Import required

# Good - string references avoid imports
class NewEntity(BaseModel):
    user = relationship("User", back_populates="entities")  # String reference
```

### Issue: Missing cascade deletes

**Problem**: Deleting parent records leaves orphaned child records

**Solution**: Use appropriate cascade options on relationships:

```python
# Bad - no cascade, orphaned records remain
class User(BaseModel):
    entities = relationship("NewEntity", back_populates="owner")

# Good - cascade deletes child records
class User(BaseModel):
    entities = relationship(
        "NewEntity",
        back_populates="owner",
        cascade="all, delete-orphan"
    )
```

### Issue: Timezone-naive datetime fields

**Problem**: Datetime fields without timezone information cause comparison issues

**Solution**: Always use timezone-aware datetime columns:

```python
# Bad - timezone-naive datetime
class NewEntity(BaseModel):
    happened_at = Column(DateTime, nullable=False)  # No timezone

# Good - timezone-aware datetime
class NewEntity(BaseModel):
    happened_at = Column(DateTime(timezone=True), nullable=False)  # With timezone
```

## Related documentation

- [Repository Layer](../repositories/README.md) - Data access patterns that work with these models
- [Services Layer](../services/README.md) - Business logic that operates on these domain entities
- [Schemas Layer](../schemas/README.md) - Request/response validation for these models
- [Main Architecture](../README.md) - How models fit into the overall application architecture
