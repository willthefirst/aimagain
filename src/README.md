# Source code: Core application architecture

The `src/` directory contains the complete implementation of the Aimagain chat application, organized using a **layered architecture** pattern that separates concerns across API, business logic, data access, and presentation layers.

## 🎯 Core philosophy: Clean layered architecture

This codebase follows a **clean architecture** approach where dependencies flow inward toward the core business logic, making the application maintainable, testable, and easy to understand.

### What we do ✅

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

### What we don't do ❌

- **Direct database access from routes**: All database operations go through repositories
- **Business logic in API routes**: Routes only handle HTTP concerns, business logic stays in services
- **Circular dependencies**: Each layer only depends on layers below it
- **Mixed concerns**: Templates, API logic, and business logic are kept separate

**Example**: Don't put business logic directly in routes:

```python
# ❌ Wrong - business logic in route
@router.post("/conversations")
async def create_conversation(data: dict, session: AsyncSession = Depends(get_db_session)):
    # Complex validation and business logic here
    new_conv = Conversation(**data)
    session.add(new_conv)
    # ... more business logic
    return new_conv

# ✅ Correct - delegate to service layer
@router.post("/conversations")
async def create_conversation(data: ConversationCreate, service: ConversationService = Depends()):
    return await conversation_service.create_conversation(data)
```

## 🏗️ Architecture: Simple layered design

**API → Services → Repositories → Database**

- **API** handles HTTP requests and responses
- **Services** contain business logic
- **Repositories** handle database operations
- **Database** stores the data

Everything else (schemas, models, templates) supports these main layers.

## 📋 Layer responsibilities matrix

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

## 📁 Directory structure

**Core files:**

- `main.py` - FastAPI application entry point
- `db.py` - Database configuration and sessions
- `auth_config.py` - Authentication setup

**Main layers:**

- `api/` - HTTP API layer
  - `routes/` - Route definitions by domain
  - `common/` - Shared utilities and decorators
- `services/` - Business logic layer
  - `conversation_service.py`, `user_service.py`, etc.
  - `dependencies.py` - Service dependency injection
- `repositories/` - Data access layer
  - `conversation_repository.py`, `user_repository.py`, etc.
  - `base.py` - Common repository patterns
- `models/` - Database models
  - `user.py`, `conversation.py`, `message.py`, etc.
  - `base.py` - Common model fields

**Supporting components:**

- `schemas/` - Request/response validation (Pydantic)
- `templates/` - HTML templates for web interface
- `middleware/` - Cross-cutting concerns (presence tracking)
- `logic/` - Data processing utilities
- `core/` - Configuration and utilities

## 🔧 Implementation patterns

### Adding a new domain entity

1. **Create the model** in `models/[entity].py`:

```python
from .base import Base

class NewEntity(Base):
    __tablename__ = "new_entities"
    name: str = Column(String(100), nullable=False)
    # ... other fields
```

2. **Create the repository** in `repositories/[entity]_repository.py`:

```python
from .base import BaseRepository
from ..models.new_entity import NewEntity

class NewEntityRepository(BaseRepository[NewEntity]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, NewEntity)

    async def find_by_name(self, name: str) -> Optional[NewEntity]:
        # Custom query methods here
```

3. **Create the service** in `services/[entity]_service.py`:

```python
class NewEntityService:
    def __init__(self, repo: NewEntityRepository):
        self.repo = repo

    async def create_entity(self, data: NewEntityCreate) -> NewEntity:
        # Business logic here
        return await self.repo.create(data.dict())
```

4. **Add API routes** in `api/routes/[entity].py`:

```python
from ...services.new_entity_service import NewEntityService

router = APIRouter()

@router.post("/new-entities")
async def create_new_entity(
    data: NewEntityCreate,
    service: NewEntityService = Depends(get_new_entity_service)
):
    return await service.create_entity(data)
```

### Dependency injection pattern

All services and repositories use dependency injection through FastAPI's `Depends()`:

```python
# In services/dependencies.py
async def get_conversation_service(
    repo: ConversationRepository = Depends(get_conversation_repository)
) -> ConversationService:
    return ConversationService(repo)

# In API routes
@router.post("/conversations")
async def create_conversation(
    data: ConversationCreate,
    service: ConversationService = Depends(get_conversation_service)
):
    return await service.create_conversation(data)
```

## 🚨 Common issues and solutions

### Issue: Circular imports between layers

**Problem**: Trying to import services in repositories or models in API routes
**Solution**: Always import from lower layers only. Use dependency injection for higher-layer dependencies.

```python
# ❌ Wrong - importing from higher layer
from ..services.user_service import UserService  # In a repository

# ✅ Correct - inject dependency
class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
```

### Issue: Business logic in API routes

**Problem**: Complex validation or business rules directly in route handlers
**Solution**: Move all business logic to service layer, keep routes thin

```python
# ❌ Wrong - business logic in route
@router.post("/conversations")
async def create_conversation(data: dict, session: AsyncSession = Depends()):
    if not data.get("title"):
        raise HTTPException(400, "Title required")
    # ... more business logic

# ✅ Correct - delegate to service
@router.post("/conversations")
async def create_conversation(
    data: ConversationCreate,  # Schema handles validation
    service: ConversationService = Depends()
):
    return await service.create_conversation(data)  # Service handles business logic
```

### Issue: Direct database access from routes

**Problem**: Using database session directly in API routes
**Solution**: Always go through repository layer for data access

```python
# ❌ Wrong - direct database access
@router.get("/users/{user_id}")
async def get_user(user_id: int, session: AsyncSession = Depends()):
    user = await session.get(User, user_id)
    return user

# ✅ Correct - use repository
@router.get("/users/{user_id}")
async def get_user(
    user_id: int,
    service: UserService = Depends()
):
    return await service.get_user(user_id)
```

## 📚 Related documentation

- [API Layer Documentation](api/README.md) - HTTP routes and validation patterns
- [Services Layer Documentation](services/README.md) - Business logic organization
- [Models Documentation](models/README.md) - Database schema and relationships
- [Repository Pattern Documentation](repositories/README.md) - Data access patterns
- [Testing Strategy](../tests/README.md) - How to test each layer
