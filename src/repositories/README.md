# Repositories layer: Data access and database operations

The `repositories/` directory contains the **data access layer** of the application, implementing the **repository pattern** to encapsulate database operations, provide clean abstractions over SQLAlchemy queries, and maintain separation between business logic and data persistence.

## Core philosophy: Clean data access abstraction

Repositories provide **focused, domain-specific data access** methods that encapsulate complex SQLAlchemy queries while maintaining transaction boundaries and providing type-safe interfaces for the [`logic/`](../logic/README.md) layer (which owns the commit).

### What we do

- **Query encapsulation**: Complex SQLAlchemy queries wrapped in meaningful method names
- **Relationship loading**: Explicit control over eager/lazy loading using `selectinload` and `joinedload`
- **Transaction management**: coordinate database operations within logic-controlled transactions (repositories `flush()` but never `commit()` — the calling logic handler owns the commit)
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

## Layer organization

Repositories follow the [cluster pattern](../README.md#domain-entities-and-the-cluster-pattern):

- One cluster directory per domain entity (`<entity>/`). Each holds `<entity>_repository.py` (the repository class with its data-access methods). Clusters with non-obvious queries (eager-loading choices, ownership filters, soft-delete semantics, multi-step writes) earn a colocated `test_<entity>_repository.py` — `providers/test_provider_repository.py` is the worked example. Thin pass-through clusters whose methods are direct ORM wrappers can lean on route-level coverage; the test exists when a future reader would otherwise have to read the SQL to learn the contract. Per-entity query patterns, eager-loading choices, cascade behavior, and read filters live inside the cluster, with a `<entity>/README.md` if anything is non-obvious.
- Parent-level shared tier:
  - `base.py` — `BaseRepository` generic with common session management. Every repository inherits from it.
  - `dependencies.py` — FastAPI `Depends()` providers that wire each repository to the request-scoped session. Adding a new repository means appending one provider here.
  - `audit_repository.py` (+ its `test_audit_repository.py`) — append-only audit log, cross-cutting infrastructure consumed by every entity's logic handlers. Lives flat at the layer's shared tier (matching `src/logic/audit.py` and `src/models/audit_log.py`) rather than in a cluster, because audit isn't a domain entity in its own right.

A repository does not import from a peer cluster's repository; if logic needs to coordinate two entities, that orchestration belongs in the [logic layer](../logic/README.md), not in repositories.

## Implementation patterns

### Creating a new repository

1. **Define the repository** in `[entity]/[entity]_repository.py`:

```python
from typing import Sequence
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import [Entity]
from ..base import BaseRepository

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
        return await self._list(
            select([Entity]).order_by([Entity].created_at.desc())
        )

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

3. **Use in logic handlers**:

```python
async def handle_list_[entity](
    repo: [Entity]Repository,
    requesting_user: User,
):
    items = await repo.list_[entity](exclude_user=requesting_user)
    return {"items": items, "current_user": requesting_user}
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

Repositories receive sessions via dependency injection. Logic handlers control the commit:

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

# Logic handlers commit (or let exceptions abort the transaction)
async def handle_create_entity(data, user, repo: [Entity]Repository):
    entity = await repo.create_entity(**data.model_dump(), owner_id=user.id)
    await repo.session.commit()  # logic owns the commit
    return entity
```

### CRUD primitives on `BaseRepository`

`BaseRepository` carries protected primitives that capture the exact shapes every resource repo writes by hand. They own only the flush/refresh ritual; they never call `commit()`. Use them when your method body is one of these shapes plus *zero* other operations; otherwise write the body explicitly.

| Primitive | Shape it captures |
| --- | --- |
| `_get_by_id(Model, id)` | `select(Model).filter(Model.id == id).scalars().first()` |
| `_list(stmt, *, limit=None, offset=None)` | `execute(stmt); return result.scalars().all()` — generic on `T` so `_list(select(Post))` returns `Sequence[Post]`. Filter/order/join logic stays inline in the calling method; pagination kwargs are optional and default to "return everything." |
| `_count(stmt)` | `select(func.count()).select_from(stmt.subquery()); return scalar_one()` — caller passes the same `select(...)` they'd pass to `_list`; filters, joins, and `.distinct()` are preserved by the subquery wrapper. |
| `_persist_new(obj)` | `session.add(obj); flush; refresh; return obj` |
| `_add_child(parent, "collection", child)` | `getattr(parent, "collection").append(child); flush; refresh(child); return child` |
| `_patch(obj, **fields)` | skip-`None` `setattr` loop, then `flush; refresh; return obj` |
| `_delete(obj)` | `session.delete(obj); flush` |

`_list` and `_count` are the binding targets for pagination + total-count endpoints. The primitives are in place, but no endpoint adopts them today — each per-endpoint wire-contract decision (return `{items, total}`? thread `limit`/`offset`?) is independent of having the primitives exist.

When *not* to delegate:

- `get_X_by_<field>` lookups that are not by primary key — write them out.
- `update_X` methods that need a richer skip predicate (e.g. `PostRepository.update_post`'s "skip fields not in this kind's spec") — write them out and document why.
- Any flow that wires up multiple related rows in one flush — e.g. `PostRepository.create_post` calls `_attach_detail` before delegating to `_persist_new`, but the attachment itself stays explicit.

```python
# Typical resource repo using the primitives:
async def get_by_id(self, provider_id: UUID) -> Provider | None:
    return await self._get_by_id(Provider, provider_id)

async def create_provider(self, user_id: UUID, **fields) -> Provider:
    return await self._persist_new(Provider(owner_id=user_id, **fields))

async def add_licensure(self, provider, **fields) -> ProviderLicensure:
    return await self._add_child(provider, "licensures", ProviderLicensure(**fields))

async def update_provider(self, provider, **fields) -> Provider:
    return await self._patch(provider, **fields)

async def delete_provider(self, provider) -> None:
    await self._delete(provider)
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

# Business logic in the logic handler
async def handle_list_entities_for_user(user: User, repo: [Entity]Repository):
    if not _check_permission(user):  # Business logic in the handler
        raise ForbiddenError(detail="Not allowed")
    return await repo.list_entities()
```

## Tests

Colocated tests live alongside the repositories:

- `test_base.py` — exercises `_list` (pagination via `limit` / `offset`, statement-order preservation, empty result) and `_count` (filters, joins with `.distinct()`); the other `BaseRepository` primitives are covered transitively by per-resource repo tests.
- `test_audit_repository.py` — exercises append-only writes, FK `SET NULL` on actor delete, and list-by-resource ordering against the in-memory test DB.
- `test_post_repository.py` — exercises parent + detail create/update/delete for every registered kind (`client_referral`, `provider_availability`), including a raw-SQL DELETE that proves the FK CASCADE fires (not just the ORM cascade). Also covers the `posts.kind` CHECK constraint rejecting unregistered kinds (including the retired `note` kind). Relies on `PRAGMA foreign_keys = ON` being set globally by the test engine fixture. Detail-row construction goes through `make_<kind>_detail` factories in [`tests/helpers.py`](../../tests/helpers.py) so spec-required fields are filled with valid defaults; tests override only what they're asserting on. Per-kind dispatch in `_attach_detail` and `update_post` is registry-driven via `POST_KINDS` / `POST_KIND_BY_DETAIL_MODEL` from [`src/models/posts/post_kinds.py`](../models/posts/post_kinds.py); the registry-consistency tests live with the registry, not here.
- `test_provider_repository.py` — exercises `Provider` CRUD, cascade delete (parent + sub-rows gone in one shot), `list_providers` filtering through licensures (license_type, issuing_state, AND-composed, `.distinct()` de-dup), and CRUD round-trips for each sub-table (licensure, education, certification). Sub-row construction uses `make_provider_*` factories in [`tests/helpers.py`](../../tests/helpers.py).

When adding a new repository method, extend (or create) `src/repositories/test_<repo_name>.py` and exercise it via the `db_test_session_manager` fixture from [`tests/fixtures.py`](../../tests/fixtures.py).

## Related documentation

- [Models Layer](../models/README.md) - Database models and relationships
- [Logic Layer](../logic/README.md) - Business logic layer that uses repositories
- [Main Architecture](../README.md) - Overall application architecture
