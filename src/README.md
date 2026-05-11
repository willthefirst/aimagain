# Source code: Core application architecture

The `src/` directory contains the complete implementation of the application, organized using a **layered architecture** pattern that separates concerns across API, business logic, data access, and presentation layers. Currently this is a bare-bones skeleton with user authentication and basic user routes, ready to be extended with new features.

## Core philosophy: Clean layered architecture

This codebase follows a **clean architecture** approach where dependencies flow inward toward the core business logic, making the application maintainable, testable, and easy to understand.

### What we do

- **Layer separation**: Clear boundaries between API, logic, repositories, and models
- **Dependency injection**: Repositories are injected rather than directly instantiated
- **Domain-driven design**: Business logic is encapsulated in `logic/<entity>_processing.py` `handle_*` functions
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

# 3. implement business logic as a handler in logic/
async def handle_create_new_feature(
    data: NewFeatureCreate,
    user: User,
    repo: NewFeatureRepository,
) -> NewFeature:
    feature = await repo.create(data, owner_id=user.id)
    await repo.session.commit()  # logic owns the commit
    return feature

# 4. add API routes
@router.post("/new-features")
async def create_new_feature(
    data: NewFeatureCreate,
    user: User = Depends(current_active_user),
    repo: NewFeatureRepository = Depends(get_new_feature_repository),
):
    return await handle_create_new_feature(data, user, repo)
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

# Good - delegate to a logic handler that owns the commit
@router.post("/[entities]")
async def create_entity(
    data: EntityCreate,
    user: User = Depends(current_active_user),
    repo: EntityRepository = Depends(get_entity_repository),
):
    return await handle_create_entity(data, user, repo)
```

## Architecture: Simple layered design

**API -> Logic -> Repositories -> Database**

- **API** handles HTTP requests and responses
- **Logic** contains business logic, orchestration, and owns the transaction commit
- **Repositories** handle database operations
- **Database** stores the data

Everything else (schemas, models, templates) supports these main layers. There is no `services/` layer — see [Error handling](#error-handling) below for how domain errors flow.

## Layer responsibilities matrix

**Rule:** each layer may only import from layers listed in its `Dependencies` column. Crossing the table upward (e.g. a repository importing a logic module) is a layering violation — fix the design, don't add the import.

| Layer            | Status   | Responsibility                                              | Example Files       | Dependencies                          |
| ---------------- | -------- | ----------------------------------------------------------- | ------------------- | ------------------------------------- |
| **API**          | active   | HTTP handling, routing, validation                          | `api/routes/*.py`   | Logic, Repositories, Schemas          |
| **Logic**        | active   | Business logic, orchestration, transaction commit           | `logic/*.py`        | Repositories, Schemas, Models, API common exceptions + pure helpers (projections) |
| **Repositories** | active   | Data access, queries                                        | `repositories/*.py` | Models, Database                      |
| **Models**       | active   | Database schema, relationships                              | `models/*.py`       | SQLAlchemy                            |
| **Schemas**      | active   | Request/response validation                                 | `schemas/*.py`      | Pydantic, Models (enums + registries only), Core (`form_fields.HtmlPattern` marker only) |
| **Middleware**   | empty    | Cross-cutting concerns                                      | `middleware/*.py`   | FastAPI                               |
| **Core**         | active   | Configuration, utilities                                    | `core/*.py`         | None                                  |

### Error handling

Logic-layer `handle_*` functions raise the API exception subclasses directly — `NotFoundError`, `ForbiddenError`, `BadRequestError`, etc. from [`src/api/common/exceptions.py`](api/common/exceptions.py). Those are `HTTPException` subclasses, so the `@handle_route_errors` decorator passes them through unchanged. fastapi-users exceptions raised during registration/auth get translated by `handle_fastapi_users_error`. Everything else becomes a generic 500.

There is no separate domain-error hierarchy (e.g. `ServiceError`, `BusinessRuleError`). An earlier scaffold of that pattern lived under `src/services/exceptions.py` but was never raised by any logic handler — it was deleted in the cleanup that closed issue #107. If a future entity needs a domain-error type that isn't a 1:1 fit for the existing API exceptions, add it next to where it's raised; don't reintroduce a top-level hierarchy.

## Domain entities and the cluster pattern

The layer matrix above is one axis of the architecture; the other is the **domain entity**. Every domain entity has a 1:1 directory presence at each layer that touches it, and every layer has a *shared tier* at the parent level for genuinely cross-entity infrastructure. The directory listing IS the entity registry — `ls src/<layer>/` is the source of truth for what entities exist.

**The import rule.** A file in `<layer>/<entity>/` may import from its own cluster and from the layer's shared tier (anything at `<layer>/`'s parent level). Cross-cluster imports (a file in cluster A importing from cluster B) are forbidden — fix the design or hoist the shared piece into the parent. Two lint checks enforce this:

- [`scripts/dev/template_imports_check.py`](../scripts/dev/template_imports_check.py) — Jinja `{% extends/include/from/import %}` directives across `src/templates/`.
- [`scripts/dev/python_cluster_imports_check.py`](../scripts/dev/python_cluster_imports_check.py) — Python `from ...` imports across the clustered Python layers. Cluster directories are auto-discovered (any subdirectory with `.py` files) so new entities and new clusters pick up the rule for free.

Both run as part of `dev lint` and as pre-commit hooks scoped to the relevant file globs.

**Documentation locality.** Parent READMEs describe the layer's contract — what a repository is, what it depends on, what the shared tier provides — but do not enumerate which entities currently exist or list per-entity contents. Entity-specific facts live in the cluster's own README (`<layer>/<entity>/README.md`); when an entity has nothing surprising to say at a layer, no cluster README is required. This is the [grammar-not-alphabet rule](../CLAUDE.md#grammar-not-alphabet) applied to README content.

## Directory structure

**Core files** at `src/`:

- `main.py` - FastAPI application entry point
- `db.py` - Database configuration and sessions
- `auth_config.py` - Authentication setup (FastAPI-Users with JWT cookies)

**Layers** (each with its own README describing the layer's contract):

- `api/` - HTTP API layer
- `logic/` - Business logic, orchestration, transaction commit
- `repositories/` - Data access
- `models/` - Database models
- `schemas/` - Request/response validation (Pydantic)
- `templates/` - HTML templates (Jinja2 + HTMX)
- `middleware/` - Cross-cutting concerns
- `core/` - Configuration, utilities

Each clustered layer has the shape `<layer>/<entity>/...` for entity-specific code plus parent-level files for the shared tier; see the layer's README for its contract.

## Implementation patterns

### Adding a new domain entity

This is the cross-module checklist. The detailed step-by-step (with code snippets) for each layer lives in that layer's own README — follow the links so the recipe stays a single source of truth (see [`../CLAUDE.md`](../CLAUDE.md)). For each step, also add or extend the colocated `test_*.py` and update the relevant README — see [Domain entities and the cluster pattern](#domain-entities-and-the-cluster-pattern) for whether entity-specific docs go in the layer's parent README or in a `<layer>/<entity>/README.md`. Where the layer is already clustered (`templates/`, partly `models/`), create the entity's cluster directory and its README; where the layer is still flat, follow the `<entity>_<role>.py` file convention.

0. **Read [`api/routes/RESOURCE_GRAMMAR.md`](api/routes/RESOURCE_GRAMMAR.md) first.** It dictates the URL shape, the PUT-vs-PATCH rule, the optional publication-lifecycle pattern, and the subresource conventions every resource MUST follow. Decide whether the resource adopts the publication lifecycle, then identify state axes, field clusters, and any subresources you'll need before touching the layers below.
1. **Model** — define the SQLAlchemy class. See [`models/README.md`](models/README.md#implementation-patterns).
2. **Migration** — generate and run an Alembic migration for the new table. See [`../alembic/README.md`](../alembic/README.md).
3. **Schema** — add Pydantic request/response shapes. See [`schemas/README.md`](schemas/README.md#implementation-patterns).
4. **Repository** — add custom data-access methods (the standard CRUD shapes are handled by the framework via `BaseRepository`'s public aliases — see [`repositories/README.md`](repositories/README.md#crud-primitives-on-baserepository)).
5. **Entity spec** — declare `<ENTITY>_ENTITY: EntitySpec` in [`src/api/common/specs/<entity>.py`](api/common/README.md#entityspec). Carries identity, audit binding, route opt-ins, write_authz, body adapters, templates, filters, discriminator (for polymorphism), parent (for owned subentities), private-field visibility, state axes, related-list subresources, M:N relations. Add a colocated `test_<entity>.py` asserting the spec declares the right values.
6. **Logic** — write bespoke `handle_*` functions in `src/logic/<entity>/<entity>_processing.py` *only* for verbs that have rules the generic framework can't subsume (custom auth predicates beyond `write_authz`, multi-step writes, edge mutations). The standard create / update / delete shape is provided by [`src/logic/_generic.py`](logic/README.md) — `mount_entity` auto-binds `make_<verb>_handler(<ENTITY>_ENTITY)` for any opted-in standard verb without an explicit handler. Raise the API exceptions from [`src/api/common/exceptions.py`](api/common/exceptions.py) directly (`NotFoundError`, `ForbiddenError`, etc.) — see [Error handling](#error-handling).
7. **Route** — create `src/api/routes/<entity>.py` and call `mount_entity(router, <ENTITY>_ENTITY, handlers={...}, owned_subentities=(...))` once. The dispatcher stitches factory-built handlers onto the route module (auto-detected from the caller frame) as `_handle_<verb>_<entity>` so contract-test patches resolve through it. See [`api/routes/README.md`](api/routes/README.md#implementation-patterns).
8. **Template (if rendering HTML)** — add the Jinja2 template. See [`templates/README.md`](templates/README.md).

For entities with a discriminator-based polymorphic shape (like `Post` / `kind`), see [`models/posts/post_kinds.py`](models/posts/post_kinds.py) for the registry pattern. The entity's `EntitySpec` then sets `discriminator=<your-registry>`, and the framework's `handle_create` / `handle_update` automatically dispatch through it to find the per-kind detail model. Adding a new discriminator value is a one-file change in the registry plus the per-variant Pydantic classes and templates — no edits in routes, repositories, or logic.

### Dependency injection pattern

Repositories use dependency injection through FastAPI's `Depends()`. Routes inject the repository, then call the logic handler — there is no service layer in between for current entities.

```python
# In repositories/dependencies.py
async def get_user_repository(
    session: AsyncSession = Depends(get_db_session),
) -> UserRepository:
    return UserRepository(session)

# In API routes — route injects the repo and calls the logic handler
@router.get("/users")
async def list_users(
    user: User = Depends(current_active_user),
    user_repo: UserRepository = Depends(get_user_repository),
):
    return await handle_list_users(user_repo, requesting_user=user)
```

## Common issues and solutions

### Issue: Circular imports between layers

**Problem**: Trying to import logic from repositories, or models from API routes the wrong way.
**Solution**: Always import from lower layers only. Use dependency injection for higher-layer dependencies.

```python
# Bad - importing from higher layer
from ..logic.user_processing import handle_list_users  # In a repository

# Good - inject dependency
class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
```

### Issue: Business logic in API routes

**Problem**: Complex validation or business rules directly in route handlers
**Solution**: Move all business logic to a `handle_*` function in `logic/`, keep routes thin

```python
# Bad - business logic in route
@router.post("/[entities]")
async def create_entity(data: dict, session: AsyncSession = Depends()):
    if not data.get("name"):
        raise HTTPException(400, "Name required")
    # ... more business logic

# Good - delegate to logic handler
@router.post("/[entities]")
async def create_entity(
    data: EntityCreate,  # Schema handles validation
    user: User = Depends(current_active_user),
    repo: EntityRepository = Depends(get_entity_repository),
):
    return await handle_create_entity(data, user, repo)  # logic handler owns the commit
```

### Issue: Direct database access from routes

**Problem**: Using database session directly in API routes
**Solution**: Always go through the repository layer for data access; routes call into `logic/` for anything beyond a trivial fetch.

```python
# Bad - direct database access
@router.get("/users/{user_id}")
async def get_user(user_id: int, session: AsyncSession = Depends()):
    user = await session.get(User, user_id)
    return user

# Good - use repository (and logic if there is real orchestration)
@router.get("/users/{user_id}")
async def get_user(
    user_id: UUID,
    user_repo: UserRepository = Depends(get_user_repository),
):
    return await user_repo.get_user_by_id(user_id)
```

## Related documentation

- [API Layer Documentation](api/README.md) - HTTP routes and validation patterns
- [Logic Layer Documentation](logic/README.md) - Business logic, orchestration, transaction commits
- [Models Documentation](models/README.md) - Database schema and relationships
- [Repository Pattern Documentation](repositories/README.md) - Data access patterns
- [Testing Strategy](../tests/README.md) - How to test each layer
