# Routes

Thin HTTP adapters. One route file per resource. CRUD-shaped routes declare an `EntitySpec` in [`../specs/`](../specs/) and call `mount_entity(router, ENTITY, handlers={...})`; the dispatcher reads the spec and fires the right `mount_*` helper for each opted-in verb.

The URL shape, lifecycle, and subresource conventions every resource MUST follow live in [`RESOURCE_GRAMMAR.md`](RESOURCE_GRAMMAR.md). The dispatcher contract lives in [`../../framework/dispatch/README.md`](../../framework/dispatch/README.md). This file documents only what's specific to this directory.

## Adding a CRUD resource

1. Declare the spec in [`../specs/<entity>.py`](../specs/) with a colocated `test_<entity>.py`.
2. Create `<entity>.py` here. Call `mount_entity` once; framework verbs auto-bind via `make_<verb>_handler(<ENTITY>_ENTITY)` and get stitched onto the route module as `_handle_<verb>_<entity>` for contract-test patches.
3. Register the router in [`../../main.py`](../../main.py). Order matters when literal segments would shadow parametric ones.
4. Add `test_<entity>.py` for resource-specific behavior (the framework verbs are already covered under [`../../framework/dispatch/`](../../framework/dispatch/)).

```python
from src.framework import make_entity_router
from src.framework.dispatch.resource_routes import mount_entity
from src.domain.specs.<entity> import <ENTITY>_ENTITY

router = make_entity_router(<ENTITY>_ENTITY)
<entity>_api_router = router.router

mount_entity(router, <ENTITY>_ENTITY)
```

## Sub-resources

Declare the child entity with `parent=PARENT_ENTITY` on its spec; pass it through `owned_subentities=` on the parent's `mount_entity` call. Each opted-in verb on the child auto-binds `make_<verb>_handler(child)`; supply `handlers["<child.name>.<verb>"]` only when the child needs a bespoke handler.

## Bespoke routes

The grammar fits resource-shaped CRUD. These stay hand-written:

| Route(s) | File | Reason |
|---|---|---|
| `POST /auth/register` | `auth_routes.py` | Auth-flow protocol (token issuance, fastapi-users hooks). |
| `GET /auth/{register,login,forgot-password,reset-password/{token}}` | `auth_pages.py` | Pure form rendering. |
| `GET /users/me`, `GET /users/me/providers` | `users.py` | Singleton aliases — mounted via `singleton_alias=` on the existing `mount_detail` / `mount_related_list`. |
| `POST/DELETE/GET /users/me/favorites[/{provider_id}]` | `favorites.py` | M:N edge add/remove — no `mount_*` helper for edge mutations. |
| `GET /`, `GET /health` | `../../main.py` | Utility endpoints. |

## Tests

Colocated `test_<resource>.py`. Shared fixtures from [`../../../tests/fixtures.py`](../../../tests/fixtures.py); user helpers from [`../../../tests/helpers.py`](../../../tests/helpers.py). Contract pairs for HTML forms and htmx-driven actions live in [`../../../tests/test_contract/`](../../../tests/test_contract/README.md) — required per the [grammar](RESOURCE_GRAMMAR.md).
