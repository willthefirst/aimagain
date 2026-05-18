# Framework: the domain-agnostic library

Everything in `src/framework/` is generic — nothing here knows what a "user" or "post" is. Specs are read as parameters; per-entity files live in [`../domain/`](../domain/).

The framework groups its code by concern:

- **[`dispatch/`](dispatch/README.md)** — turns specs into HTTP routes. `EntitySpec`, the `mount_entity` dispatcher and the `mount_*` family, generic CRUD handlers + the `make_<verb>_handler` factories, `BaseRouter`.
- **[`persistence/`](persistence/README.md)** — SQLAlchemy + DI primitives. `Base` / `BaseModel`, `BaseRepository`, the polymorphic `DiscriminatorRegistry`, the FastAPI `Depends` resolver registry.
- **[`audit/`](audit/README.md)** — the audit framework. `AuditLog` model, `AuditRepository`, the `record_audit` / `record_audit_for` helpers, the `mutate(...)` context manager, the `AuditedResource` / `EdgeAudit` bindings.
- **[`http/`](http/README.md)** — cross-cutting HTTP plumbing. `APIException` subclasses, response helpers, form parsing, decorators, ASGI middleware.
- **[`rendering/`](rendering/README.md)** — Jinja + form rendering. Templating env, view projections, the schema-driven form-field markers.

Plus three flat-at-root single-file modules used by everything:

- `authz.py` — auth predicates (`is_owner_or_admin`, `is_admin`, `is_self_or_admin`) + the matching raising forms.
- `schema_validators.py` — reusable Pydantic field validators (zip, phone, etc.).
- `config.py` — settings singleton.

## What you usually need

For day-to-day work, three entry points cover most cases:

- **Mounting an entity's routes** — call `mount_entity(router, ENTITY)` from the route file. See [`dispatch/README.md`](dispatch/README.md).
- **Auditing a mutation** — wrap the handler body in `async with mutate(...)` or call `record_audit(...)` directly. See [`audit/README.md`](audit/README.md).
- **Custom repository queries** — extend `BaseRepository` in a per-entity repo class. See [`persistence/README.md`](persistence/README.md).

Per-mount docstrings in [`dispatch/resource_routes.py`](dispatch/resource_routes.py) are the canonical reference for required spec fields and exact handler kwargs.

## Import discipline

Framework code reads specs **via parameters, not via imports** — nothing under this directory imports from `src/domain/` at module load time. The one exception is the `AuditLog` SQLAlchemy class at `src/domain/models/__init__.py`, which the audit framework reads directly.

The auth-resolved actor is typed via the structural [`Actor` protocol](actor.py), so generic handlers (`dispatch/handlers.py`), audit (`audit/core.py`), authz predicates (`authz.py`), and chrome context (`http/responses.py`) take `Actor` / `Actor | None` instead of a concrete domain `User`. The domain's `User` model satisfies the protocol by structure; tests can pass a `SimpleNamespace`.
