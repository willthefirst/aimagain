# Services layer: Domain exception hierarchy

> **Status (2026-05): this directory exists solely to hold the `ServiceError` exception hierarchy.** Every other file that previously lived here (`user_service.py`, `dependencies.py`, `provider.py`) was a stub with zero importers and was deleted in the cleanup that closed issue #103.
>
> Business logic and the transaction commit for every current entity live in [`src/logic/<entity>_processing.py`](../logic/README.md), not here. See [Services vs. logic](../README.md#services-vs-logic-de-facto-convention) in the parent README for the full convention. If a future entity grows cross-cutting business rules that don't fit a single `handle_*` function, that's when a real `<Entity>Service` belongs in this directory — and at that point the layer matrix in [`../README.md`](../README.md) should be updated to reflect it.
>
> The name `services/` (and the `ServiceError` naming) is a slight misnomer given current usage; renaming/relocating the exception hierarchy is tracked separately as a follow-up to keep this PR's blast radius small.

## What's actually in here

- `exceptions.py` — domain exception hierarchy. Imported by `src/api/common/decorators.py` and `src/api/common/exceptions.py` to map domain errors to HTTP responses.
- `__init__.py` — package marker.

## Exception hierarchy

```python
class ServiceError(Exception):
    """Base. status_code=500."""

class UserNotFoundError(ServiceError):       # 404
class NotAuthorizedError(ServiceError):      # 403
class BusinessRuleError(ServiceError):       # 400 — business-rule violation
class ConflictError(ServiceError):           # 409 — state conflict
class DatabaseError(ServiceError):           # 500 — DB-level failure
```

`handle_*` functions in `src/logic/` raise these; the API layer catches them and converts the carried `status_code` into the HTTP response.

## Tests

No colocated tests yet — the exception classes are pure data and are exercised indirectly by the API decorator tests. Add `test_exceptions.py` here if behavior beyond `__init__` is ever introduced.

## Related documentation

- [Logic Layer](../logic/README.md) — where these exceptions are raised.
- [API Common](../api/common/README.md) — where these exceptions are caught and mapped to HTTP.
- [Main Architecture](../README.md) — services-vs-logic convention.
