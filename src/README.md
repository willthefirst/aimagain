# Source code: Core application architecture

The `src/` directory contains the complete implementation of the application, organized using a **layered architecture** pattern that separates concerns across API, business logic, data access, and presentation layers. Currently this is a bare-bones skeleton with user authentication and basic user routes, ready to be extended with new features.

## Core philosophy: Clean layered architecture

This codebase follows a **clean architecture** approach where dependencies flow inward toward the core business logic, making the application maintainable, testable, and easy to understand.

### What we do

- **Layer separation**: Clear boundaries between API, services, repositories, and models
- **Dependency injection**: Services and repositories are injected rather than directly instantiated
- **Domain-driven design**: Business logic is encapsulated in service classes
- **Schema validation**: All API inputs/outputs are validated using Pydantic schemas
- **Database abstraction**: Repository pattern abstracts database operations

**Example**: Adding a new feature follows the pattern:

```python
# 1. define the data model
class NewFeature(Base):
    __tablename__ = "new_features"
    # ... fields

# 2. create repository for data access
class NewFeatureRepository(BaseRepository[NewFeature]):
    # ... data access methods

# 3. implement business logic in service
class NewFeatureService:
    def __init__(self, repo: NewFeatureRepository):
        self.repo = repo
    # ... business logic

# 4. add API routes
@router.post("/new-features")
async def create_new_feature(data: NewFeatureSchema, service: NewFeatureService = Depends()):
    return await service.create(data)
```

### What we don't do

- **Direct database access from routes**: All database operations go through repositories
- **Business logic in API routes**: Routes only handle HTTP concerns, business logic stays in services
- **Circular dependencies**: Each layer only depends on layers below it
- **Mixed concerns**: Templates, API logic, and business logic are kept separate

**Example**: Don't put business logic directly in routes:

```python
# Bad - business logic in route
@router.post("/[entities]")
async def create_entity(data: dict, session: AsyncSession = Depends(get_db_session)):
    # Complex validation and business logic here
    new_entity = Entity(**data)
    session.add(new_entity)
    # ... more business logic
    return new_entity

# Good - delegate to service layer
@router.post("/[entities]")
async def create_entity(data: EntityCreate, service: EntityService = Depends()):
    return await service.create_entity(data)
```

## Architecture: Simple layered design

**API -> Services -> Repositories -> Database**

- **API** handles HTTP requests and responses
- **Services** contain business logic
- **Repositories** handle database operations
- **Database** stores the data

Everything else (schemas, models, templates) supports these main layers.

## Layer responsibilities matrix

| Layer            | Responsibility                     | Example Files       | Dependencies         |
| ---------------- | ---------------------------------- | ------------------- | -------------------- |
| **API**          | HTTP handling, routing, validation | `api/routes/*.py`   | Services, Schemas    |
| **Services**     | Business logic, coordination       | `services/*.py`     | Repositories, Models |
| **Repositories** | Data access, queries               | `repositories/*.py` | Models, Database     |
| **Models**       | Database schema, relationships     | `models/*.py`       | SQLAlchemy           |
| **Schemas**      | Request/response validation        | `schemas/*.py`      | Pydantic             |
| **Logic**        | Data transformation, processing    | `logic/*.py`        | Services, Schemas    |
| **Middleware**   | Cross-cutting concerns             | `middleware/*.py`   | FastAPI              |
| **Core**         | Configuration, utilities           | `core/*.py`         | None                 |

## Directory structure

**Core files:**

- `main.py` - FastAPI application entry point
- `db.py` - Database configuration and sessions
- `auth_config.py` - Authentication setup (FastAPI-Users with JWT cookies)

**Main layers:**

- `api/` - HTTP API layer
  - `routes/` - Route definitions by domain
  - `common/` - Shared utilities and decorators
- `services/` - Business logic layer
  - `user_service.py` - User-related business logic
  - `dependencies.py` - Service dependency injection
- `repositories/` - Data access layer
  - `user_repository.py` - User data access
  - `base.py` - Common repository patterns
- `models/` - Database models
  - `user.py` - User model (with `username` field)
  - `base.py` - Common model fields (UUID, timestamps, soft delete)

**Supporting components:**

- `schemas/` - Request/response validation (Pydantic)
- `templates/` - HTML templates for web interface (Jinja2 + HTMX)
- `middleware/` - Cross-cutting concerns (currently empty)
- `logic/` - Data processing utilities
- `core/` - Configuration and utilities

## Implementation patterns

### Adding a new domain entity

This is the cross-module checklist. The detailed step-by-step (with code snippets) for each layer lives in that layer's own README — follow the links so the recipe stays a single source of truth (see [`../CLAUDE.md`](../CLAUDE.md)). For each step, also add or extend the colocated `test_*.py` and update the README in that directory.

1. **Model** — define the SQLAlchemy class. See [`models/README.md`](models/README.md#implementation-patterns).
2. **Migration** — generate and run an Alembic migration for the new table. See [`../alembic/README.md`](../alembic/README.md).
3. **Schema** — add Pydantic request/response shapes. See [`schemas/README.md`](schemas/README.md#implementation-patterns).
4. **Repository** — add data-access methods. See [`repositories/README.md`](repositories/README.md#implementation-patterns).
5. **Service** — implement business logic and authorization. See [`services/README.md`](services/README.md#implementation-patterns).
6. **Route** — wire up the HTTP endpoint that delegates to the service. See [`api/routes/README.md`](api/routes/README.md#implementation-patterns).
7. **Template (if rendering HTML)** — add the Jinja2 template. See [`templates/README.md`](templates/README.md).

### Dependency injection pattern

All services and repositories use dependency injection through FastAPI's `Depends()`:

```python
# In services/dependencies.py
async def get_user_service(
    repo: UserRepository = Depends(get_user_repository)
) -> UserService:
    return UserService(repo)

# In API routes
@router.get("/users")
async def list_users(
    service: UserService = Depends(get_user_service)
):
    return await service.list_users()
```

## Common issues and solutions

### Issue: Circular imports between layers

**Problem**: Trying to import services in repositories or models in API routes
**Solution**: Always import from lower layers only. Use dependency injection for higher-layer dependencies.

```python
# Bad - importing from higher layer
from ..services.user_service import UserService  # In a repository

# Good - inject dependency
class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
```

### Issue: Business logic in API routes

**Problem**: Complex validation or business rules directly in route handlers
**Solution**: Move all business logic to service layer, keep routes thin

```python
# Bad - business logic in route
@router.post("/[entities]")
async def create_entity(data: dict, session: AsyncSession = Depends()):
    if not data.get("name"):
        raise HTTPException(400, "Name required")
    # ... more business logic

# Good - delegate to service
@router.post("/[entities]")
async def create_entity(
    data: EntityCreate,  # Schema handles validation
    service: EntityService = Depends()
):
    return await service.create_entity(data)  # Service handles business logic
```

### Issue: Direct database access from routes

**Problem**: Using database session directly in API routes
**Solution**: Always go through repository layer for data access

```python
# Bad - direct database access
@router.get("/users/{user_id}")
async def get_user(user_id: int, session: AsyncSession = Depends()):
    user = await session.get(User, user_id)
    return user

# Good - use repository
@router.get("/users/{user_id}")
async def get_user(
    user_id: int,
    service: UserService = Depends()
):
    return await service.get_user(user_id)
```

## Related documentation

- [API Layer Documentation](api/README.md) - HTTP routes and validation patterns
- [Services Layer Documentation](services/README.md) - Business logic organization
- [Models Documentation](models/README.md) - Database schema and relationships
- [Repository Pattern Documentation](repositories/README.md) - Data access patterns
- [Testing Strategy](../tests/README.md) - How to test each layer
