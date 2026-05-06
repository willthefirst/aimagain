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

## Domain entity matrix

| Model        | Primary Purpose                                  | Key Fields                                                          | Unique Constraints |
| ------------ | ------------------------------------------------ | ------------------------------------------------------------------- | ------------------ |
| **User**     | Authentication and identity                      | username                                                            | username, email    |
| **Post**     | User-authored content (parent of per-kind detail) | kind (CHECK `'client_referral', 'provider_availability'`), owner_id (FK) | —                  |
| **ClientReferralDetail** | Per-kind detail for `kind='client_referral'` posts. Carries the full intake-form fields per [`../../notes/forms_spec.md`](../../notes/forms_spec.md) Form 1 (location, demographics, description, services, insurance). Enum columns CHECK against tuples in [`post_enums.py`](post_enums.py); the `desired_times` multi-select is a JSON column whose vocabulary is enforced by Pydantic on the wire (no SQL CHECK against array members). The remaining `services` multi-select follows in a separate change. | post_id (PK + FK to posts, CASCADE), description, location_*, desired_times (JSON), client_dem_ages, language_preferred, services_psychotherapy_modality, insurance | — |
| **ProviderAvailabilityDetail** | Per-kind detail for `kind='provider_availability'` posts. Carries the full intake-form fields per [`../../notes/forms_spec.md`](../../notes/forms_spec.md) Form 2 (provider info, location, availability, featured services, insurance). Enum columns CHECK against tuples in [`post_enums.py`](post_enums.py); the `desired_times` multi-select is a JSON column whose vocabulary is enforced by Pydantic on the wire (no SQL CHECK against array members). The remaining `services` and `settings` multi-selects follow in a separate change. | post_id (PK + FK to posts, CASCADE), practice_name, available_providers, location_*, in_person_sessions, virtual_sessions, desired_times (JSON), treatment_modality, client_focus, age_group, non_english_services, payment_situation, sliding_scale, cost | — |
| **AuditLog** | Append-only mutation record (RESOURCE_GRAMMAR.md:135) | actor_id (FK, SET NULL), resource_type, resource_id, action, before/after (JSON) | —                  |

### Parent / per-kind-detail split

`Post` is the parent table for any post-shaped resource. It carries identity, ownership, timestamps, and a `kind` discriminator. Kind-specific fields live in their own detail table keyed by `post_id` (PK + FK with `ON DELETE CASCADE`).

Kinds today: `client_referral` (→ `client_referral_details`) and `provider_availability` (→ `provider_availability_details`). Both carry the scalar (single-value) fields from the intake forms in [`../../notes/forms_spec.md`](../../notes/forms_spec.md) plus the `desired_times` multi-select (stored as JSON; vocabulary enforced on the wire by Pydantic). The remaining multi-select fields (`services`, `settings`) follow in a separate change. The retired `note` kind (title + body) was removed once the two real kinds landed and the registry made the cleanup a one-line change. Detail rows have no `id` of their own — `post_id` is both PK and FK, enforcing 1:1.

### The `post_kinds` registry

The set of allowed kinds — and the per-kind detail relationship + field metadata used across the codebase — lives in [`post_kinds.py`](post_kinds.py) as `REGISTERED_KINDS: dict[str, KindSpec]`. Every cross-cutting site reads from it:

- `Post.__table_args__` builds its `CheckConstraint` from `kind_check_sql()` — the SQL is derived from `KIND_NAMES`.
- The route's `Literal[*KIND_NAMES]` for `GET /posts/form?kind=…` is derived.
- The form-template selection in `src/api/routes/posts.py` reads `spec.create_template` / `spec.edit_template`.
- `src/repositories/post_repository.py:_attach_detail` looks up by detail-class via `KIND_BY_DETAIL_MODEL`; `update_post` writes to `spec.detail_relationship` for the post's kind.
- `src/logic/post_processing.py:handle_create_post` and `handle_update_post` dispatch via `REGISTERED_KINDS[payload.kind]` instead of `isinstance` ladders.
- `src/schemas/post.py:_flatten_post_to_dict` reads the relationship + field tuple from the registry (so `PostRead`, `PostAuditSnapshot` flatten through it).
- `src/templates/posts/list.html` receives `post_kinds` in its context and renders the per-kind "New X" links from it.

Adding a kind is therefore: (1) a registry entry in `post_kinds.py`, (2) a new detail model file + a `relationship(...)` line on `Post`, (3) the four Pydantic variant classes in `src/schemas/post.py`, (4) the per-kind templates under `src/templates/posts/`, (5) an Alembic migration. Removing a kind is the inverse. No edits in routes, repositories, or logic — those layers are registry-driven. The consistency tests in [`test_post_kinds.py`](test_post_kinds.py) guard against re-encoding the kind set inline anywhere new.

## Directory structure

**Core model files:**

- `user.py` - User authentication and profile (extends FastAPI Users)
- `post.py` - Parent row for posts: kind discriminator + owner FK; one detail table per kind. CHECK constraint is derived from `post_kinds.py`.
- `post_kinds.py` - `REGISTERED_KINDS` registry: per-kind detail model, relationship name, field tuple (derived from the model's columns via `_detail_fields(model)` so the registry never drifts from the schema), templates, list label. Single source of truth for the kind set.
- `post_enums.py` - Controlled-vocabulary tuples shared by per-kind detail columns (`US_STATES`, `LOCATION_AVAILABILITY_OPTIONS`, `CLIENT_AGE_GROUPS`, `LANGUAGE_PREFERRED_OPTIONS`, `INSURANCE_OPTIONS`, `DESIRED_TIME_SLOTS` plus its `DESIRED_TIME_DAYS` / `DESIRED_TIME_PARTS` axes) plus a `check_in_tuple_sql` helper that renders DB-level CHECK fragments from them, and matching `*_LABELS` dicts (`LOCATION_AVAILABILITY_LABELS`, `CLIENT_AGE_GROUP_LABELS`, `LANGUAGE_PREFERRED_LABELS`, `INSURANCE_LABELS`, `DESIRED_TIME_SLOT_LABELS` + per-axis `DESIRED_TIME_DAY_LABELS` / `DESIRED_TIME_PART_LABELS`) that hold the human-readable label for each value. Single source of truth — `src/schemas/post.py` derives its `Literal[*TUPLE]`s from these tuples and the form-render macros in `src/templates/posts/_form_macros.html` iterate over them via Jinja globals. Two guardrail tests in `src/schemas/test_post.py` keep the schema literals + the label dicts in lockstep with the tuples. Lives in its own leaf module so the detail models can depend on it without a circular import through `post_kinds`.
- `client_referral_detail.py` - `kind='client_referral'` detail; 1:1 with `posts` via `post_id`. Columns cover the scalar fields from `notes/forms_spec.md` Form 1 plus the `desired_times` JSON multi-select; enum columns CHECK against `post_enums.py` (the JSON column does not — vocabulary is enforced on the wire by Pydantic).
- `provider_availability_detail.py` - `kind='provider_availability'` detail; 1:1 with `posts` via `post_id`. Columns cover the scalar fields from `notes/forms_spec.md` Form 2 plus the `desired_times` JSON multi-select; enum columns CHECK against `post_enums.py` (the JSON column does not — vocabulary is enforced on the wire by Pydantic).

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

## Tests

- `test_post_kinds.py` — guards the `post_kinds` registry as the single source of truth: asserts `KIND_NAMES` matches the registry, the rendered `kind_check_sql()` matches what `Post.__table_args__` actually produces, the route's `Literal[*KIND_NAMES]` reflects the registry, the inverse `KIND_BY_DETAIL_MODEL` lookup is well-formed, the per-kind relationship-name convention holds, and `KindSpec.detail_fields` exactly matches the underlying detail model's column list (so the introspection-driven derivation can't silently drift from the schema). If a future change re-encodes the kind set inline somewhere, the relevant test here fails.

Most other model behavior is exercised indirectly through repository and route tests. Add `src/models/test_<model_name>.py` when a model carries non-trivial logic (computed fields, validators, custom `__init__`, etc.) that warrants direct coverage.

When changing a model's schema, generate an Alembic migration as part of the same change — see [`../../CLAUDE.md`](../../CLAUDE.md).

## Related documentation

- [Repository Layer](../repositories/README.md) - Data access patterns that work with these models
- [Logic Layer](../logic/README.md) - Business logic that operates on these domain entities
- [Schemas Layer](../schemas/README.md) - Request/response validation for these models
- [Main Architecture](../README.md) - How models fit into the overall application architecture
