# Source code: two buckets

The `src/` tree is organized into two top-level concepts:

- **`framework/`** — the domain-agnostic library. Dispatch helpers (`mount_entity`, the generic `handle_*` family), the audit framework, repository primitives, auth predicates, response/forms/projections helpers, Jinja templating setup, the SQLAlchemy `Base` / `BaseModel` / `AuditLog` infra, the polymorphic discriminator registry. Nothing in `framework/` knows what a "user" or "post" is — it reads specs as parameters.
- **`domain/`** — everything entity-specific, layered by purpose. Each layer is clustered per entity.

```
src/
├── framework/           ← AGNOSTIC: read by all entities; depends on none
└── domain/              ← DOMAIN: every entity-specific file
    ├── specs/<entity>.py             ← EntitySpec declarations
    ├── models/<entity>/              ← SQLAlchemy classes (clustered)
    ├── logic/<entity>/               ← handlers + repository + schema
    ├── routes/<entity>.py            ← thin route file: mount_entity(spec)
    └── templates/<entity>/           ← Jinja templates
```

Plus three loose files at `src/`:
- **`main.py`** — application entry point.
- **`db.py`** — database engine / session factory.
- **`auth_config.py`** — fastapi-users setup.

## How the buckets relate

```
domain/specs/<entity>.py       ← declare what exists
        ↓
framework/                     ← reads specs, generates dispatch, provides shared primitives
        ↓
domain/logic/<entity>/         ← per-entity bespoke handlers + custom-SQL repos + Pydantic schemas
domain/models/<entity>/        ← SQLAlchemy classes
domain/routes/<entity>.py      ← thin glue; calls mount_entity(spec) once
domain/templates/<entity>/     ← Jinja templates
```

A spec is read at three sites:

1. **Route mounting** — `mount_entity(router, USER_ENTITY, handlers={...})` reads `routes`, `state_axes`, `subresources`, `auth_deps`, `auth_policy`, `audit`, etc. and binds the right `mount_*` helper for each opted-in verb.
2. **Generic handlers** — `handle_create(spec)` / `handle_update` / `handle_delete` / `handle_detail` / `handle_list` in `framework/dispatch/handlers.py` consult `spec.audit`, `spec.write_authz`, `spec.model`, `spec.list_exclude_self`, `spec.parent`, etc. for the framework-owned work.
3. **Bespoke handlers** — domain handlers (e.g. `handle_set_user_activation` in `domain/logic/users/handlers.py`) read `USER_ENTITY.state_axis("activation").action`, `USER_ENTITY.audit.type`, etc. so per-handler audit/state declarations stay in one place.

## Adding a new domain entity

The work is concentrated. For each step, also add or extend the colocated `test_*.py`.

0. **Read [`domain/routes/RESOURCE_GRAMMAR.md`](domain/routes/RESOURCE_GRAMMAR.md) first.** URL shape, PUT-vs-PATCH rule, subresource convention.
1. **Model** — define the SQLAlchemy class in [`domain/models/<entity>/`](domain/models/README.md).
2. **Migration** — generate an Alembic migration. See [`../alembic/README.md`](../alembic/README.md).
3. **Logic cluster** — create `domain/logic/<entity>/` with `schema.py` (Pydantic types), `repository.py` (only methods with custom SQL — the framework calls `BaseRepository`'s public aliases for the standard shapes; see [`framework/README.md`](framework/README.md)), and `handlers.py` for bespoke business logic the framework can't subsume (custom auth, multi-step writes, edge mutations).
4. **Spec** — declare `<ENTITY>_ENTITY: EntitySpec` in [`domain/specs/<entity>.py`](domain/specs/) carrying identity, audit binding, route opt-ins, write_authz, body adapters, templates, filters, discriminator (for polymorphism), parent (for owned subentities), private-field visibility, state axes, related-list subresources, M:N relations. Add a colocated `test_<entity>.py` asserting the spec declares the right values.
5. **Route** — create `domain/routes/<entity>.py` and call `mount_entity(router, <ENTITY>_ENTITY, handlers={...}, owned_subentities=(...))` once. The dispatcher stitches factory-built handlers onto the route module (auto-detected from the caller frame) as `_handle_<verb>_<entity>` so contract-test patches resolve through it. See [`domain/routes/README.md`](domain/routes/README.md).
6. **Template (if rendering HTML)** — add the Jinja2 template in [`domain/templates/<entity>/`](domain/templates/README.md).

For polymorphic entities (`Post` / `kind`), see [`domain/models/posts/post_kinds.py`](domain/models/posts/post_kinds.py). The spec sets `discriminator=<registry>` and the framework's `handle_create` / `handle_update` dispatch through it automatically.

## Error handling

Domain handlers raise the API exception subclasses directly — `NotFoundError`, `ForbiddenError`, `BadRequestError`, etc. from [`framework/http/exceptions.py`](framework/http/exceptions.py). Those are `HTTPException` subclasses, so the `@handle_route_errors` decorator passes them through unchanged. fastapi-users exceptions raised during registration/auth get translated by `handle_fastapi_users_error`. Everything else becomes a generic 500.

There is no separate domain-error hierarchy. If a future entity needs a domain-error type that isn't a 1:1 fit, add it next to where it's raised; don't reintroduce a top-level hierarchy.

## Import discipline

The structure encodes the dependency direction:

- **`framework/` does not import from `domain/`.** The framework is generic; specs are the input, domain code is the consumer. Framework code reads specs *via parameters*, not via imports.
- **`domain/specs/` is read-only for consumers.** Spec files import models, schemas (for adapters), and framework types — never from `domain/logic/<entity>/` directly. Per-entity callables that specs need to reference (state-axis handlers, detail-extras callables) are declared as dotted-path strings (`handler_path`, `detail_extras_path`) and resolved lazily by the framework at mount time. This keeps `specs → logic` from closing a cycle with `logic → specs`.
- **`domain/logic/<entity>/` may import from `framework/`, `domain/specs/`, `domain/models/`, and from another `domain/logic/<other>/` cluster when it needs that entity's type** (e.g. `domain/logic/users/handlers.py` reads `domain/logic/providers/repository.ProviderRepository` to fetch a user's providers). Cross-entity handler-to-handler imports are discouraged but not lint-enforced — the layer collapse made cross-entity type references frequent enough that an automated rule would mostly produce false positives.
- **`domain/routes/` may import from anywhere** but is intentionally thin — one `mount_entity(...)` call per file plus the rare hand-written endpoint.
- **`domain/models/` follows the strict cluster rule** (enforced by [`../scripts/dev/python_cluster_imports_check.py`](../scripts/dev/python_cluster_imports_check.py)): a model file in one cluster may not import from a sibling cluster. Cross-entity FKs reference each other via SQLAlchemy strings, not Python imports.

## Where things are

| You're looking for                                              | It's at                                                              |
| --------------------------------------------------------------- | -------------------------------------------------------------------- |
| Declarations of every entity                                    | [`domain/specs/`](domain/specs/) — one file per entity               |
| `EntitySpec` dataclass + its friends                            | [`framework/dispatch/entity_spec.py`](framework/dispatch/entity_spec.py)               |
| Route mounting helpers (`mount_entity`, `mount_*`)              | [`framework/dispatch/resource_routes.py`](framework/dispatch/resource_routes.py)       |
| Generic handlers (`handle_create`, `handle_list`, ...)          | [`framework/dispatch/handlers.py`](framework/dispatch/handlers.py)                     |
| `BaseRepository` primitives                                     | [`framework/persistence/base_repository.py`](framework/persistence/base_repository.py)       |
| Audit framework (`mutate`, `record_audit`, `AuditAction`)       | [`framework/audit/core.py`](framework/audit/core.py)                           |
| Auth predicates (`is_owner_or_admin`, `is_admin`)               | [`framework/authz.py`](framework/authz.py)                           |
| Per-entity handlers (the bespoke ones)                          | [`domain/logic/<entity>/handlers.py`](domain/logic/)                 |
| Per-entity custom queries                                       | [`domain/logic/<entity>/repository.py`](domain/logic/)               |
| Per-entity Pydantic shapes                                      | [`domain/logic/<entity>/schema.py`](domain/logic/)                   |
| Route files (one per entity, thin)                              | [`domain/routes/<entity>.py`](domain/routes/)                        |
| Jinja templates                                                 | [`domain/templates/<entity>/`](domain/templates/)                    |
| SQLAlchemy classes                                              | [`domain/models/<entity>/`](domain/models/)                          |
