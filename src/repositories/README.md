# Repositories layer: Data access and database operations

The `repositories/` directory contains the **data access layer** of the application, implementing the **repository pattern** to encapsulate database operations, provide clean abstractions over SQLAlchemy queries, and maintain separation between business logic and data persistence.

## Core philosophy: Clean data access abstraction

Repositories provide **focused, domain-specific data access** methods that encapsulate complex SQLAlchemy queries while maintaining transaction boundaries and providing type-safe interfaces for the service layer.

### What we do

- **Query encapsulation**: Complex SQLAlchemy queries wrapped in meaningful method names
- **Relationship loading**: Explicit control over eager/lazy loading using `selectinload` and `joinedload`
- **Transaction management**: Coordinate database operations within service-controlled transactions
- **Type safety**: Return proper domain models with full type annotations
- **Domain-specific methods**: Business-relevant query methods like `list_users()`

**Example**: Repository method with proper query structure:

```python
class UserRepository(BaseRepository):
    async def get_user_by_username(self, username: str) -> User | None:
        """Retrieves a user by their username."""
        stmt = select(User).filter(User.username == username)
        result = await self.session.execute(stmt)
        return result.scalars().first()
```

### What we don't do

- **Business logic**: Repositories only handle data access, no business rule enforcement
- **Transaction control**: Services manage transaction boundaries (commit/rollback)
- **Error handling with business context**: Raw database errors bubble up to services
- **Cross-domain queries**: Each repository focuses on its primary domain entity

**Example**: Don't implement business logic in repositories:

```python
# Bad - business logic in repository
class [Entity]Repository:
    async def create_entity_if_allowed(self, data, user: User):
        if not self._check_permission(user):  # Business rule checking
            raise BusinessError("Not allowed")

# Good - pure data access
class [Entity]Repository:
    async def create_entity(self, **kwargs) -> [Entity]:
        # Only data persistence operations
        new_entity = [Entity](**kwargs)
        self.session.add(new_entity)
        await self.session.flush()
        return new_entity
```

## Architecture: Repository pattern with dependency injection

**Services -> Repositories -> SQLAlchemy -> Database**

Each repository manages one primary domain entity with related data access operations.

## Repository responsibility matrix

| Repository         | Primary Entity | Key Responsibilities                                                          |
| ------------------ | -------------- | ----------------------------------------------------------------------------- |
| **UserRepository** | User           | User lookup, listing, activation toggle, hard delete                          |

## Directory structure

**Core repository files:**

- `user_repository.py` - User data access and lookup

**Infrastructure:**

- `base.py` - BaseRepository with common session management
- `dependencies.py` - FastAPI dependency injection for all repositories

## Implementation patterns

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
async def get_entity_by_id(self, entity_id: UUID) -> [Entity] | None:
    stmt = select([Entity]).filter([Entity].id == entity_id)
    result = await self.session.execute(stmt)
    return result.scalars().first()

# Detailed query - with relationships loaded
async def get_entity_details(self, entity_id: UUID) -> [Entity] | None:
    stmt = (
        select([Entity])
        .filter([Entity].id == entity_id)
        .options(
            selectinload([Entity].related_items).joinedload(RelatedItem.owner),
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
async def create_entity(self, **data) -> [Entity]:
    entity = [Entity](**data)
    self.session.add(entity)
    await self.session.flush()  # Make available in transaction
    return entity

# Services control commit/rollback
class [Entity]Service:
    async def create_entity(self, data):
        try:
            entity = await self.repo.create_entity(**data)
            await self.session.commit()  # Service commits
            return entity
        except Exception:
            await self.session.rollback()  # Service handles errors
            raise
```

## Common issues and solutions

### Issue: N+1 query problems

**Problem**: Accessing relationships in loops causes multiple database queries
**Solution**: Use explicit relationship loading in repository methods

```python
# Bad - causes N+1 queries
entities = await repo.list_entities()
for entity in entities:
    print(entity.related_items)  # Each access hits database

# Good - eager load relationships
async def list_entities(self) -> Sequence[[Entity]]:
    stmt = (
        select([Entity])
        .options(selectinload([Entity].related_items))
        .order_by([Entity].created_at.desc())
    )
    result = await self.session.execute(stmt)
    return result.scalars().all()
```

### Issue: Session lifecycle confusion

**Problem**: Repository methods trying to commit transactions
**Solution**: Let services control transaction boundaries

```python
# Bad - repository committing
async def create_user(self, data):
    user = User(**data)
    self.session.add(user)
    await self.session.commit()  # Repository shouldn't commit
    return user

# Good - repository only persists
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
# Bad - business logic in repository
async def get_entities_for_user(self, user: User):
    if not self._check_permission(user):  # Business rule
        return []

# Good - simple data access in repository
async def list_entities(self) -> Sequence[[Entity]]:
    stmt = select([Entity]).order_by([Entity].created_at.desc())
    result = await self.session.execute(stmt)
    return result.scalars().all()

# Business logic in service
class [Entity]Service:
    async def get_entities_for_user(self, user: User):
        if not self._check_permission(user):  # Business logic in service
            return []
        return await self.repo.list_entities()
```

## Tests

**TODO** — no colocated tests yet. When adding a repository method, create `src/repositories/test_<repo_name>.py` and exercise it against the in-memory test database via the `db_test_session_manager` fixture (from [`tests/fixtures.py`](../../tests/fixtures.py)).

## Related documentation

- [Models Layer](../models/README.md) - Database models and relationships
- [Services Layer](../services/README.md) - Business logic layer that uses repositories
- [Main Architecture](../README.md) - Overall application architecture
