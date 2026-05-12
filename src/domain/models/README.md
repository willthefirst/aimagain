# Models layer: Database schema and domain entities

The `models/` directory contains **SQLAlchemy data models** that define the database schema and constraints for the application, implementing a **relational domain model** with clear entity boundaries.

## Core philosophy: Domain-driven data modeling

Models represent **business entities** with clear relationships, enforcing data integrity through database constraints.

### What we do

- **Domain entity modeling**: Each model represents a clear business concept (User, Post)
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

## Domain entities

The directory listing IS the registry: `ls .` shows every cluster + the shared parent-level files. Per-entity facts (fields, constraints, cascade behavior, parent/detail splits) live in each cluster's own README when there's something non-obvious to say.

### Polymorphic / per-kind detail (the post-shape)

When an entity has multiple variants whose fields differ, the parent table carries identity + a discriminator column, and each variant's fields live in its own detail table keyed by `<parent>_id` (PK + FK with `ON DELETE CASCADE`). The registry of variants is a `DiscriminatorRegistry[<Spec>]` instance under the parent's cluster (e.g. [`posts/post_kinds.py`](posts/post_kinds.py) for `Post`). The framework's `handle_create` / `handle_update` dispatch through the registry; no `isinstance` ladders.

A new variant is: (1) a registry entry, (2) a new detail-model file in the cluster + a `relationship(...)` on the parent, (3) the matching Pydantic variants under `domain/logic/<entity>/schema.py`, (4) per-variant templates under `domain/templates/<entity>/`, (5) an Alembic migration. No edits in routes, repositories, or logic — those layers are registry-driven.

For the post-specific instance of the registry pattern (the full list of cross-cutting sites that read `POST_KINDS`, the discriminator-specific cleanup story), see [`posts/README.md`](posts/README.md).

## Layer organization

Models follow the per-entity cluster pattern declared in [`../../README.md`](../../README.md):

- One cluster directory per domain entity (`<entity>/`). Each holds the SQLAlchemy table classes for that entity (parent table, sub-records, type registries if discriminator-based) plus colocated tests. Per-entity schema specifics, relationships, cascade behavior, and any "adding a variant" recipe live inside the cluster, with a `<entity>/README.md` describing what's there.
- Parent-level shared tier:
  - `enums.py` — Controlled-vocabulary tuples + `*_LABELS` dicts + a `check_in_tuple_sql` helper that renders DB-level `CHECK` fragments from a tuple. The single source of truth that schemas (`Literal[*TUPLE]`), form macros (Jinja globals), and DB constraints all derive from. Lives at the parent level because 2+ clusters depend on it — and is a *leaf* (no internal imports), so any cluster can import from it without cycling back through cluster code.
  - `__init__.py` — Re-exports model classes and constants, including `Base`, `BaseModel`, `metadata`, and `AuditLog` from [`src/framework/`](../../framework/) (the generic SQLAlchemy infra lives in the framework; the hub re-exports it for compatibility). External code should always import from `src.domain.models` (e.g. `from src.domain.models import Post, POST_KINDS`); the `__init__.py` keeps that surface stable across cluster moves.

A model in cluster A does not import from cluster B; if two clusters need a shared primitive, hoist it to the parent level (the path `enums.py` took).

## Implementation patterns

### Creating a new model

1. **Define the model** in `[entity].py`:

```python
from sqlalchemy import Column, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid
from src.framework.base_model import BaseModel

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

### Issue: Missing parent-side relationship breaks flush ordering

**Problem**: A model with a `ForeignKey` column but no `relationship()` may be flushed before its parent in a single-transaction seed, producing `FOREIGN KEY constraint failed` errors that look unrelated to ORM modeling.

**Why**: SQLAlchemy's flush-ordering graph is built from `relationship()` declarations, not raw FK columns. Without a relationship at either end, the unit of work has no signal to flush parent before child. SQLite's `PRAGMA foreign_keys = ON` (set in `tests/fixtures.py`) then rejects the out-of-order INSERT.

**Solution**: Add `relationship(...)` at one end of every domain-edge FK — either the child's many-to-one (`provider.user`) or the parent's collection (`user.providers`); either is enough to fix flush ordering. The exception is denormalized historical references (e.g. `audit_log.actor_id`) — those go on the `ALLOWED_BARE_FKS` allowlist in `test_fk_relationship_coverage.py` with a one-line justification.

```python
# Bad - bare FK; flush order is undefined, single-transaction seeds may fail
class Provider(BaseModel):
    owner_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)

# Good - relationship covers the FK; flush order is parent-then-child
class Provider(BaseModel):
    owner_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    user = relationship("User")
```

## Tests

- [`posts/test_post_kinds.py`](posts/test_post_kinds.py) — guards the `post_kinds` registry as the single source of truth (colocated with the registry it tests). See [`posts/README.md`](posts/README.md) for the per-test rundown.
- `test_fk_relationship_coverage.py` — guards against the flush-ordering trap above: walks every `ForeignKey` on every mapped class and asserts that at least one end declares a covering `relationship()`, or that the FK appears in the in-file `ALLOWED_BARE_FKS` allowlist with a one-line justification. The allowlist's value is the reason — that documentation is half the point.
- [`providers/test_provider_models.py`](providers/test_provider_models.py) and [`providers/test_provider_enums.py`](providers/test_provider_enums.py) — direct DB-layer + label-coverage tests for the providers cluster (colocated with the cluster they cover). See [`providers/README.md`](providers/README.md) for the per-test rundown.

Most other model behavior is exercised indirectly through repository and route tests. Add `src/domain/models/test_<model_name>.py` when a model carries non-trivial logic (computed fields, validators, custom `__init__`, etc.) that warrants direct coverage.

When changing a model's schema, generate an Alembic migration as part of the same change — see [`../../../CLAUDE.md`](../../../CLAUDE.md).

## Related documentation

- [Per-entity logic](../logic/) - Repositories, handlers, and Pydantic schemas that operate on these models
- [Routes](../routes/README.md) - HTTP entry points that exercise these models via handlers
- [Top-level architecture](../../README.md) - How models fit into the `framework/` vs `domain/` split
