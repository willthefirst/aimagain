# Logic: Processing layer between routes and services

The `logic/` directory contains **processing functions** that handle the orchestration of business operations, serving as the coordination layer between API routes and services while managing error handling, validation, and data transformation for specific use cases.

## Core philosophy: Business operation orchestration

Logic modules handle **complex business workflows** that require coordination between multiple services, proper error handling, and data transformation, providing a clean separation between HTTP concerns (routes) and pure business logic (services).

### What we do

- **Operation orchestration**: Coordinate complex workflows involving multiple services
- **Error translation**: Convert service exceptions into appropriate route-level responses
- **Data transformation**: Transform route input into service method parameters
- **Business rule validation**: Apply operation-specific business rules and constraints
- **Logging and monitoring**: Provide detailed logging for business operations

**Example**: User listing orchestration with error handling:

```python
async def handle_list_users(
    user_repo: UserRepository,
    requesting_user: User,
) -> dict:
    """Orchestrate user listing."""
    users_list = await user_repo.list_users(exclude_user=requesting_user)
    return {"users": users_list, "current_user": requesting_user}
```

### What we don't do

- **Direct database access**: Database operations stay in repositories/services
- **HTTP response creation**: Routes handle HTTP-specific response formatting
- **Business rule enforcement**: Core business rules stay in services
- **Authentication/authorization**: Auth logic stays in auth layer

**Example**: Don't put repository or HTTP logic in processing functions:

```python
# Bad - direct database access in logic
async def handle_list_users(session: AsyncSession, user_id: UUID):
    users = await session.execute(select(User).where(User.id != user_id))
    return users.scalars().all()

# Bad - HTTP response creation in logic
async def handle_get_entity(slug: str) -> JSONResponse:
    entity = await service.get_entity(slug)
    return JSONResponse({"entity": entity})

# Good - orchestration with proper separation
async def handle_list_users(
    user_repo: UserRepository,
    requesting_user: User,
):
    """Orchestrate user listing with filtering logic"""
    users_list = await user_repo.list_users(exclude_user=requesting_user)
    return {"users": users_list, "current_user": requesting_user}
```

## Architecture: Orchestration layer between routes and services

**Routes -> Logic -> Services -> Repositories -> Database**

Logic functions coordinate business operations without handling HTTP or database concerns.

### Transactions: logic owns the commit

`get_db_session` (in [`src/db.py`](../db.py)) yields a session and does **not** auto-commit. Repositories deliberately don't commit either — they `flush()` so the result is visible inside the open transaction, but they leave commit/rollback to the caller (see [`../repositories/README.md`](../repositories/README.md)).

There is no separate service layer — `logic/` owns the transaction commit:

```python
async def handle_set_user_activation(user_id, payload, user_repo, requesting_user):
    target = await user_repo.get_user_by_id(user_id)
    ...
    updated = await user_repo.set_user_activation(target, is_active=...)
    await user_repo.session.commit()   # logic owns the commit
    return updated
```

## Layer organization

Logic follows the [cluster pattern](../README.md#domain-entities-and-the-cluster-pattern):

- One cluster directory per domain entity (`<entity>/`). Each holds `<entity>_processing.py` with the `handle_*` functions that orchestrate that entity's operations, plus `test_<entity>_processing.py`. Per-entity workflow specifics — auth gates, audit-snapshot shapes, transaction boundaries — live inside the cluster, with a `<entity>/README.md` if anything is non-obvious.
- Parent-level shared tier:
  - `audit.py` — `record_audit(...)`, `record_audit_for(...)`, and the `mutate(...)` async context manager. Every mutation handler imports from here. The `mutate` ritual snapshots before, performs the mutation in the `async with` body, audits, and commits on clean exit; on exception the audit row and the commit are both skipped so the transaction rolls back atomically (load-bearing — an audit row must never be durable without its mutation). Non-CRUD audits (register, set-activation, etc.) use `record_audit(...)` directly.
  - `test_audit_discipline.py` — static AST check across every `*_processing.py` (recursively, so cluster directories are covered) that fails if a `handle_*` function calls `.commit()` without a `record_audit(...)`, `record_audit_for(...)`, or `mutate(...)` call. Enforces [`RESOURCE_GRAMMAR.md`'s audit rule](../api/routes/RESOURCE_GRAMMAR.md). Opt out per-handler with `audit-discipline-ignore: <reason>` in the docstring.

A processing module does not import from a peer cluster's processing module; if a workflow needs to coordinate two entities, the parent-level orchestrator is the right home (or a single handler in one cluster that uses the other cluster's repositories, when the dependency direction is clear).

## Implementation patterns

### Standard processing function structure

All processing functions follow this pattern for consistency:

```python
import logging
from typing import Any, Dict
from uuid import UUID

from src.api.common.exceptions import ForbiddenError, NotFoundError
from src.models import User
from src.repositories.[domain]_repository import [Domain]Repository

logger = logging.getLogger(__name__)


async def handle_some_operation(
    target_id: UUID,
    user: User,
    repo: [Domain]Repository,
) -> Dict[str, Any]:
    """
    Handle [operation description] orchestration.

    Raises NotFoundError / ForbiddenError directly — these are HTTPException
    subclasses, so the @handle_route_errors decorator passes them through.
    """
    logger.debug(f"Processing [operation] for user {user.id}")

    target = await repo.get_by_id(target_id)
    if target is None:
        raise NotFoundError(detail="[Entity] not found")
    if target.owner_id != user.id and not user.is_admin:
        raise ForbiddenError(detail="Only the owner or an admin can do this")

    result = await repo.do_the_thing(target)
    await repo.session.commit()
    return result
```

### Error handling pattern

Logic handlers raise the API exception classes from `src.api.common.exceptions` directly — there is no separate domain-error hierarchy. The `@handle_route_errors` decorator (applied automatically by `BaseRouter`) lets `HTTPException` subclasses pass through, translates fastapi-users exceptions, and converts anything else into a generic 500.

```python
async def handle_get_post_detail(post_id: UUID, post_repo: PostRepository):
    post = await post_repo.get_post_with_detail(post_id)
    if post is None:
        raise NotFoundError(detail="Post not found")  # → 404
    return post
```

There is no try/except boilerplate around repository calls. If a `SQLAlchemyError` escapes, the decorator's bare-`Exception` arm logs it and returns 500, which is the right outcome.

### Template context preparation pattern

For routes that render templates:

```python
async def handle_template_rendering_operation(
    request: Request,
    user: User,
    repo: [Domain]Repository,
) -> Dict[str, Any]:
    """Prepare context for template rendering."""

    # Gather all data needed for template
    primary_data = await repo.get_primary_data(user)

    # Prepare template context
    context = {
        "request": request,           # Required for FastAPI templates
        "user": user,                 # Current user context
        "primary_data": primary_data, # Main template data
        "metadata": {                 # Additional context
            "page_title": "Operation Page",
            "active_section": "operations",
        }
    }

    return context
```

## Common issues and solutions

### Issue: Logic functions becoming too complex

**Problem**: A `handle_*` function grows past ~30 lines of validation, fetches, and branching.
**Solution**: Extract private helpers (`_check_can_edit_post`, `_build_audit_snapshot`) in the same module. Don't push the work into a hypothetical service layer — there isn't one.

### Issue: swallowing errors

**Problem**: A handler catches `Exception` and returns `None` (or a default), so the route silently 200s on failure.
**Solution**: Don't catch. The decorator's bare-`Exception` arm logs and returns 500 — that's the right outcome. Only catch when you have something specific to do (e.g. translate `IntegrityError` into a `BadRequestError` with a useful message).

### Issue: Mixing HTTP concerns with business logic

**Problem**: Processing functions handle HTTP responses or request parsing
**Solution**: Keep HTTP concerns in routes, business orchestration in logic

```python
# Bad - HTTP concerns in logic
async def handle_get_users(request: Request) -> JSONResponse:
    users = await user_repo.list_users()
    return JSONResponse({"users": [user.dict() for user in users]})

# Good - return data for route to handle
async def handle_get_users(user_repo: UserRepository, requesting_user: User):
    users = await user_repo.list_users(exclude_user=requesting_user)
    return {"users": users, "current_user": requesting_user}
```

## Tests

Colocated tests live alongside the logic modules:

- `test_audit.py` — exercises the `record_audit(...)` helper: round-trip via the repo, no commit (handler owns commit), null-actor support.
- `test_audit_discipline.py` — static AST check that fails if any `handle_*` in `*_processing.py` calls `.commit()` without one of `record_audit(...)` / `record_audit_for(...)` / `mutate(...)`. Enforces `RESOURCE_GRAMMAR.md:135` so a future contributor can't silently skip the audit row. The check accepts `mutate(...)` because the context manager owns the audit + commit internally. Opt out with `audit-discipline-ignore: <reason>` in the handler's docstring.

When adding or changing a processing function, create `src/logic/test_<file>.py` next to it. Most processing functions can be unit-tested directly with mocks or with the in-memory `db_test_session_manager` fixture for the repositories they depend on.

## Related documentation

- [API Routes](../api/routes/README.md) - Route layer that calls processing functions
- [Repositories Layer](../repositories/README.md) - Repository layer accessed by handlers
- [API Common](../api/common/README.md) - Decorators + the API exception classes handlers raise
