# Logic: business logic, orchestration, and transaction commit

The `logic/` directory contains the layer that owns business logic and the transaction commit. There is no separate services layer: see [`../README.md`](../README.md) — `logic/` sits directly between routes and repositories. Logic modules orchestrate repository calls, raise API exceptions directly, and commit (or roll back) the transaction.

## Core philosophy: business logic owns the commit

Logic modules handle **complex business workflows** that need to coordinate repositories, enforce auth and business rules, and commit atomically with a matching audit row. They keep HTTP concerns out (routes own those) and database-statement details out (repositories own those).

### What we do

- **Operation orchestration**: coordinate workflows that touch one or more repositories
- **Error raising**: raise the API exception classes from [`src/api/common/exceptions.py`](../api/common/exceptions.py) directly — `NotFoundError`, `ForbiddenError`, `BadRequestError` — and let the `@handle_route_errors` decorator translate them into HTTP responses
- **Data transformation**: turn route input (validated Pydantic models) into repository calls
- **Business rule enforcement**: apply operation-specific rules and authorization checks
- **Transaction control**: own the `session.commit()` for every mutation, paired with an audit row via `record_audit(...)` / `mutate(...)`
- **Logging and monitoring**: detailed logging at the operation boundary

**Example**: User listing orchestration with error handling:

```python
async def handle_list_users(
    repo: UserRepository,
    requesting_user: User,
) -> dict:
    """Orchestrate user listing."""
    users_list = await repo.list_users(exclude_user=requesting_user)
    return {"users": users_list, "current_user": requesting_user}
```

### What we don't do

- **Direct database access**: database operations stay in repositories
- **HTTP response creation**: routes handle HTTP-specific response formatting
- **Authentication/authorization scaffolding**: the auth layer issues the user; logic handlers enforce per-operation rules using that user

**Example**: don't put repository or HTTP logic in processing functions:

```python
# Bad - direct database access in logic
async def handle_list_users(session: AsyncSession, user_id: UUID):
    users = await session.execute(select(User).where(User.id != user_id))
    return users.scalars().all()

# Bad - HTTP response creation in logic
async def handle_get_post(post_id: UUID, repo: PostRepository) -> JSONResponse:
    post = await repo.get_post_by_id(post_id)
    return JSONResponse({"post": post})

# Good - orchestration with proper separation
async def handle_list_users(
    repo: UserRepository,
    requesting_user: User,
):
    """Orchestrate user listing with filtering logic"""
    users_list = await repo.list_users(exclude_user=requesting_user)
    return {"users": users_list, "current_user": requesting_user}
```

## Architecture: routes → logic → repositories

**Routes -> Logic -> Repositories -> Database**

There is no separate service layer — see [`../README.md`](../README.md) for the canonical layer matrix. Logic functions coordinate business operations without handling HTTP or database statement details.

### Transactions: logic owns the commit

`get_db_session` (in [`src/db.py`](../db.py)) yields a session and does **not** auto-commit. Repositories deliberately don't commit either — they `flush()` so the result is visible inside the open transaction, but they leave commit/rollback to the caller (see [`../repositories/README.md`](../repositories/README.md)).

`logic/` owns the transaction commit:

```python
async def handle_set_user_activation(user_id, payload, repo, requesting_user):
    target = await repo.get_user_by_id(user_id)
    ...
    updated = await repo.set_user_activation(target, is_active=...)
    await repo.session.commit()   # logic owns the commit
    return updated
```

## Layer organization

Logic follows the [cluster pattern](../README.md#domain-entities-and-the-cluster-pattern):

- One cluster directory per domain entity (`<entity>/`). Each holds `<entity>_processing.py` with the `handle_*` functions that orchestrate that entity's operations. Clusters with non-obvious logic (auth gates, projection invariants, ownership rules) earn a colocated `test_<entity>_processing.py` that pins those rules — `providers/test_provider_processing.py` is the worked example for a heavy cluster, `users/test_user_processing.py` for a thin cluster that exists only to pin security-flavored rules. Thin pass-through clusters can lean on route-level coverage in `src/api/routes/test_<entity>.py`. Per-entity workflow specifics — auth gates, audit-snapshot shapes, transaction boundaries — live inside the cluster, with a `<entity>/README.md` if anything is non-obvious.
- Parent-level shared tier:
  - `_authz.py` — `is_admin(user)`, `is_owner(obj, user, owner_attr=...)`, and `assert_owner_or_admin(...)`. The booleans are the rule; handlers compose them to compute template-context flags (`can_edit = is_owner(post, user) or is_admin(user)`). The asserting wrapper is the same composition for use as a single-callable in `ResourceSpec.write_authz`. New authorization rules belong here, not inlined into handlers or templates.
  - `audit.py` — `record_audit(...)`, `record_audit_for(...)`, and the `mutate(...)` async context manager. Every mutation handler imports from here. The `mutate` ritual snapshots before, performs the mutation in the `async with` body, audits, and commits on clean exit; on exception the audit row and the commit are both skipped so the transaction rolls back atomically (load-bearing — an audit row must never be durable without its mutation). Non-CRUD audits (register, set-activation, etc.) use `record_audit(...)` directly. `AuditedResource` declarations historically lived next to handlers (`PROVIDER = AuditedResource(...)` in `providers/provider_processing.py`); for entities migrated to the `EntitySpec` pattern (phase 1 of #317 — today: `users`, `providers`, and the three provider-owned credentials) the declaration moves to [`src/api/common/specs/<entity>.py`](../api/common/README.md#entityspec) and handlers read it via `<ENTITY>_ENTITY.audit` (or via a thin module-level re-export for ergonomics, as `provider_processing.py` keeps). Other entities still declare `AuditedResource` inline until they migrate.
  - `test_audit_discipline.py` — static AST check across every `*_processing.py` (recursively, so cluster directories are covered) that fails if a `handle_*` function calls `.commit()` without a `record_audit(...)`, `record_audit_for(...)`, or `mutate(...)` call. Enforces [`RESOURCE_GRAMMAR.md`'s audit rule](../api/routes/RESOURCE_GRAMMAR.md). Opt out per-handler with `audit-discipline-ignore: <reason>` in the docstring.

A processing module does not import from a peer cluster's processing module; if a workflow needs to coordinate two entities, the parent-level orchestrator is the right home (or a single handler in one cluster that uses the other cluster's repositories, when the dependency direction is clear).

## Implementation patterns

### Handler kwarg naming

The repository for the resource the handler acts on is named `repo`. Additional repositories the handler needs are named by their type (`user_repo`, `audit_repo`, etc.). This keeps generic mount infrastructure able to inject `repo=` uniformly while leaving multi-repo cases legible.

```python
# Single-repo handler — primary repo is `repo`:
async def handle_get_post_detail(post_id: UUID, repo: PostRepository, ...): ...

# Multi-repo handler — primary stays `repo`, secondaries keep their typed name:
async def handle_list_user_providers(
    target_user_id: UUID,
    repo: ProviderRepository,    # primary: providers are what we list
    user_repo: UserRepository,   # secondary: needed only to verify the target user exists
    requesting_user: User,
): ...
```

The `audit_repo: AuditRepository` injected into mutation handlers is a secondary repo and follows the same rule (named by type, not collapsed to `repo`).

### Standard processing function structure

All processing functions follow this pattern for consistency:

```python
import logging
from typing import Any, Dict
from uuid import UUID

from src.api.common.exceptions import ForbiddenError, NotFoundError
from src.logic._authz import assert_owner_or_admin
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
    assert_owner_or_admin(target, user, action="do this")

    result = await repo.do_the_thing(target)
    await repo.session.commit()
    return result
```

### Error handling pattern

Logic handlers raise the API exception classes from `src.api.common.exceptions` directly — there is no separate domain-error hierarchy. The `@handle_route_errors` decorator (applied automatically by `BaseRouter`) lets `HTTPException` subclasses pass through, translates fastapi-users exceptions, and converts anything else into a generic 500.

```python
async def handle_get_post_detail(post_id: UUID, repo: PostRepository):
    post = await repo.get_post_with_detail(post_id)
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
    users = await repo.list_users()
    return JSONResponse({"users": [user.dict() for user in users]})

# Good - return data for route to handle
async def handle_get_users(repo: UserRepository, requesting_user: User):
    users = await repo.list_users(exclude_user=requesting_user)
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
