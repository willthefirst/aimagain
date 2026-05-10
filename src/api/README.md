# API layer: HTTP routes and request handling

The `api/` directory contains all HTTP-related code. Routes are **thin wrappers** that parse requests, delegate business logic to `logic/`, and format responses. They never touch repositories or sessions directly.

## Contract

- **Routes are HTTP adapters, not business logic.** Validation, authorization, and side effects live in `logic/<entity>/<entity>_processing.py` `handle_*` functions. See [`../logic/README.md`](../logic/README.md).
- **No direct data access.** Routes inject repositories via FastAPI `Depends()` and pass them through to logic handlers; they never call `session.execute(...)` themselves.
- **Form-encoded mutations + HTMX response shape are the standard** for resource routes. JSON bodies are not the default — see [`routes/README.md`](routes/README.md) and [`routes/RESOURCE_GRAMMAR.md`](routes/RESOURCE_GRAMMAR.md).
- **CRUD routes use the unified `ResourceSpec` + `mount_*` grammar** in `common/resource_routes.py`. Hand-written routes are reserved for cases the grammar doesn't fit (auth flows, singletons, idempotent state setters) — see the bespoke-routes table in [`routes/README.md`](routes/README.md#bespoke-routes).
- **Errors are raised, not caught.** Logic raises `APIException` subclasses (`NotFoundError`, `ForbiddenError`, `BadRequestError`); `BaseRouter`'s decorator chain translates them. See [`common/README.md`](common/README.md).

## Layer organization

- [`routes/`](routes/README.md) — one file per resource. Defines HTTP endpoints via `ResourceSpec` + `mount_*` (or hand-written when warranted). The route organization contract and URL grammar live there.
- [`common/`](common/README.md) — shared API infrastructure: `BaseRouter`, `ResourceSpec` and the `mount_*` family, `APIResponse` helpers, `APIException` hierarchy, the fastapi-users error translator.

## Where to look for the canonical example

Read an existing resource route alongside the contract docs:

- [`routes/users.py`](routes/users.py) and [`routes/providers.py`](routes/providers.py) for the unified `ResourceSpec` + `mount_*` pattern.
- [`routes/auth_routes.py`](routes/auth_routes.py) and [`routes/auth_pages.py`](routes/auth_pages.py) for hand-written routes that don't fit the grammar.
- [`../main.py`](../main.py) for `/` and `/health` (mounted directly on the app, not under `routes/`).

## Tests

API behavior is exercised by route-level tests colocated under [`routes/`](routes/) (e.g. `routes/test_users.py`, `routes/test_providers.py`, `routes/test_auth_routes.py`). There is no test file at this directory level — tests live next to the specific routes they cover.

Pact contract pairs for HTML forms and HX-driven buttons live under [`tests/test_contract/`](../../tests/test_contract/README.md).

## Related documentation

- [`routes/README.md`](routes/README.md) — route organization, `ResourceSpec` + `mount_*` recipe, bespoke-routes table, registration order.
- [`routes/RESOURCE_GRAMMAR.md`](routes/RESOURCE_GRAMMAR.md) — URL shape, lifecycle states, subresource conventions every resource MUST follow.
- [`common/README.md`](common/README.md) — `BaseRouter`, mount helpers, `APIResponse`, exception classes.
- [`../logic/README.md`](../logic/README.md) — what routes delegate to.
- [`../schemas/README.md`](../schemas/README.md) — request/response validation.
- [`../README.md`](../README.md) — layered architecture and dependency rules.
