# Source code: two buckets (in-flight migration)

The `src/` tree is being reorganized into **two top-level buckets**:

- **`framework/`** — the domain-agnostic library that turns spec data into a working HTTP app. Dispatch helpers (`mount_entity`, the generic `handle_*` family), the audit framework, repository primitives, auth predicates, response/forms/projections helpers, the SQLAlchemy `Base` / `BaseModel` / `AuditLog` infra, the polymorphic discriminator registry, Jinja templating setup — everything that doesn't know what a "user" or "post" is.
- **`entities/<entity>/`** — everything per-entity, fully colocated: spec, model, handlers, repository, schema, route, templates, tests. To delete an entity, delete one directory.

### Migration status

The codebase is mid-migration toward the two-bucket layout. Migrated entities live under `src/entities/`; pre-migration entities still live across the original four directories.

- **Migrated:** `favorites` → [`src/entities/favorites/`](entities/favorites/).
- **Pre-migration (will move):** `users`, `posts`, `providers` (+ credential subentities), `auth` — still split across `src/specs/`, `src/models/`, `src/domain/`, `src/api/routes/`, `src/templates/`.

While the migration is in flight, both layouts work in parallel. Cross-entity imports always go through `src/models/__init__.py` (the model hub re-exports both shapes), so no callsite cares which side of the migration an entity is on.

### Per-entity grammar (`src/entities/<entity>/`)

Each entity cluster holds:

| File | Role |
| --- | --- |
| `spec.py` | The `EntitySpec` declaration (was `src/specs/<entity>.py`). |
| `model.py` (or `models/`) | SQLAlchemy class(es). Polymorphic entities use a `models/` subdir. |
| `handlers.py` | Bespoke business-logic handlers. Omitted if the entity uses only framework-default handlers. |
| `repository.py` | Custom-SQL repo class. Omitted if the entity uses `BaseRepository` directly. |
| `schema.py` | Pydantic types the spec references. |
| `route.py` | The thin route file — `mount_entity(...)` + the rare hand-rolled endpoint. |
| `templates/*.html` | Jinja templates. Auto-discovered by [`src/framework/templating.py`](framework/templating.py)'s `PrefixLoader`; reference them as `<entity>/<name>.html`. |
| `test_*.py` | Colocated tests for the above. |

### Pre-migration buckets (transitional)

These directories still exist and hold the not-yet-migrated entities. They will be deleted as the migration completes.

- **`specs/`** — entity specs for not-yet-migrated entities.
- **`models/<entity>/`** — SQLAlchemy classes for not-yet-migrated entities. Also still holds `enums.py` (controlled vocabularies referenced across multiple entities).
- **`domain/<entity>/`** — per-entity helpers (`handlers.py`, `repository.py`, `schema.py`) for not-yet-migrated entities.
- **`api/routes/<entity>.py`** — thin route files for not-yet-migrated entities.
- **`templates/<entity>/`** — Jinja templates for not-yet-migrated entities (plus `_shared/` and `base.html` which stay here permanently).

Loose entry points: **`main.py`**, **`db.py`**, **`auth_config.py`** — application entry point, database setup, auth setup. These may move into `framework/` or `entities/auth/` in a later migration step.

## How the buckets relate

```
entities/<entity>/   ← declare what exists (spec.py) and how it behaves (handlers/repo/schema/route/templates)
       ↓
framework/           ← reads specs, generates dispatch, provides shared primitives
```

For migrated entities, every per-entity file lives in `entities/<entity>/`. For pre-migration entities, the same files are split across `specs/`, `models/<entity>/`, `domain/<entity>/`, `api/routes/`, and `templates/<entity>/`; the rules and diagrams below describe that transitional layout.

The legacy split:

```
specs/             ← declare what exists
   ↓
framework/         ← reads specs, generates dispatch, provides shared primitives
   ↓
domain/<entity>/   ← per-entity helpers + bespoke handlers, picked up by framework

api/routes/        ← thin glue; calls mount_entity(spec) once
```

A spec is read at three sites:

1. **Route mounting** — `mount_entity(router, USER_ENTITY, handlers={...})` reads `routes`, `state_axes`, `subresources`, `auth_deps`, `auth_policy`, `audit`, etc. and binds the right `mount_*` helper for each opted-in verb.
2. **Generic handlers** — `handle_create(spec)` / `handle_update` / `handle_delete` / `handle_detail` / `handle_list` in `framework/handlers.py` consult `spec.audit`, `spec.write_authz`, `spec.model`, `spec.list_exclude_self`, `spec.parent`, etc. for the framework-owned work.
3. **Bespoke handlers** — domain handlers (e.g. `handle_set_user_activation` in `domain/users/handlers.py`) read `USER_ENTITY.state_axis("activation").action`, `USER_ENTITY.audit.type`, etc. so per-handler audit/state declarations stay in one place.

## Adding a new domain entity

The work is concentrated. For each step, also add or extend the colocated `test_*.py`.

0. **Read [`api/routes/RESOURCE_GRAMMAR.md`](api/routes/RESOURCE_GRAMMAR.md) first.** URL shape, PUT-vs-PATCH rule, subresource convention.
1. **Model** — define the SQLAlchemy class in [`models/<entity>/`](models/README.md).
2. **Migration** — generate an Alembic migration. See [`../alembic/README.md`](../alembic/README.md).
3. **Domain cluster** — create `domain/<entity>/` with `schema.py` (Pydantic types), `repository.py` (only methods with custom SQL — the framework calls `BaseRepository`'s public aliases for the standard shapes; see [`framework/README.md`](framework/README.md)), and `handlers.py` for bespoke business logic the framework can't subsume (custom auth, multi-step writes, edge mutations).
4. **Spec** — declare `<ENTITY>_ENTITY: EntitySpec` in [`src/specs/<entity>.py`](specs/) carrying identity, audit binding, route opt-ins, write_authz, body adapters, templates, filters, discriminator (for polymorphism), parent (for owned subentities), private-field visibility, state axes, related-list subresources, M:N relations. Add a colocated `test_<entity>.py` asserting the spec declares the right values.
5. **Route** — create `api/routes/<entity>.py` and call `mount_entity(router, <ENTITY>_ENTITY, handlers={...}, owned_subentities=(...))` once. The dispatcher stitches factory-built handlers onto the route module (auto-detected from the caller frame) as `_handle_<verb>_<entity>` so contract-test patches resolve through it. See [`api/routes/README.md`](api/routes/README.md).
6. **Template (if rendering HTML)** — add the Jinja2 template in [`templates/<entity>/`](templates/README.md).

For polymorphic entities (`Post` / `kind`), see [`models/posts/post_kinds.py`](models/posts/post_kinds.py). The spec sets `discriminator=<registry>` and the framework's `handle_create` / `handle_update` dispatch through it automatically.

## Error handling

Domain handlers raise the API exception subclasses directly — `NotFoundError`, `ForbiddenError`, `BadRequestError`, etc. from [`framework/exceptions.py`](framework/exceptions.py). Those are `HTTPException` subclasses, so the `@handle_route_errors` decorator passes them through unchanged. fastapi-users exceptions raised during registration/auth get translated by `handle_fastapi_users_error`. Everything else becomes a generic 500.

There is no separate domain-error hierarchy. If a future entity needs a domain-error type that isn't a 1:1 fit, add it next to where it's raised; don't reintroduce a top-level hierarchy.

## Import discipline

The structure encodes the dependency direction:

- **`specs/` is read-only for consumers.** Files in `specs/` import models, schemas (for adapters), and framework types — never from `domain/<entity>/` directly. Per-entity callables that specs need to reference (state-axis handlers, detail-extras callables) are declared as dotted-path strings (`handler_path`, `detail_extras_path`) and resolved lazily by the framework at mount time. This keeps `specs → domain` from closing a cycle with `domain → specs`.
- **`framework/` does not import from `specs/` or `domain/`.** The framework is generic; specs are the input, domain code is the consumer. Framework code reads specs *via parameters*, not via imports.
- **`domain/<entity>/` may import from `framework/`, `specs/`, `models/`, and from another `domain/<other>/` cluster when it needs that entity's type** (e.g. `domain/users/handlers.py` reads `domain/providers/repository.ProviderRepository` to fetch a user's providers). Cross-entity handler-to-handler imports are discouraged but not lint-enforced — the layer collapse made cross-entity type references frequent enough that an automated rule would mostly produce false positives.
- **`api/routes/` may import from anywhere** but is intentionally thin — one `mount_entity(...)` call per file plus the rare hand-written endpoint.
- **`models/` follows the strict cluster rule** (enforced by [`../scripts/dev/python_cluster_imports_check.py`](../scripts/dev/python_cluster_imports_check.py)): a model file in one cluster may not import from a sibling cluster. Cross-entity FKs reference each other via SQLAlchemy strings, not Python imports.

## Where things are

| You're looking for                                              | It's at                                                              |
| --------------------------------------------------------------- | -------------------------------------------------------------------- |
| Declarations of every entity                                    | [`specs/`](specs/) — one file per entity                             |
| `EntitySpec` dataclass + its friends                            | [`framework/entity_spec.py`](framework/entity_spec.py)               |
| Route mounting helpers (`mount_entity`, `mount_*`)              | [`framework/resource_routes.py`](framework/resource_routes.py)       |
| Generic handlers (`handle_create`, `handle_list`, ...)          | [`framework/handlers.py`](framework/handlers.py)                     |
| `BaseRepository` primitives (`_list`, `_count`, `patch`, ...)   | [`framework/base_repository.py`](framework/base_repository.py)       |
| Audit framework (`mutate`, `record_audit`, `AuditAction`)       | [`framework/audit.py`](framework/audit.py)                           |
| Auth predicates (`is_owner_or_admin`, `is_admin`)               | [`framework/authz.py`](framework/authz.py)                           |
| Per-entity handlers (the bespoke ones)                          | [`domain/<entity>/handlers.py`](domain/)                             |
| Per-entity custom queries                                       | [`domain/<entity>/repository.py`](domain/)                           |
| Per-entity Pydantic shapes                                      | [`domain/<entity>/schema.py`](domain/)                               |
| Route files (one per entity, thin)                              | [`api/routes/<entity>.py`](api/routes/)                              |
| Jinja templates                                                 | [`templates/<entity>/`](templates/)                                  |
| SQLAlchemy classes                                              | [`models/<entity>/`](models/)                                        |
