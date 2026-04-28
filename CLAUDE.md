# Working in this repo

This file is the contract between you (the AI agent) and this codebase. Read it before any code change.

## Definition of done

For any code change in `src/<module>/`, the change is **not done** until all four are true:

1. The code change itself is in.
2. The colocated `src/<module>/README.md` reflects new/changed/removed behavior — or you have explicitly verified it is still accurate.
3. The colocated test file (`src/<module>/test_*.py`) is updated or added to cover the change.
4. `dev test` passes and `dev lint` passes.

If a module has no README or no test file yet, **create them as part of the change**. Don't defer.

A Stop hook checks the diff at end-of-turn and surfaces a reminder when source files change without their README/test. The hook is a soft prompt, not a hard block — but ignoring it should be a deliberate decision (e.g. typo fix, log message tweak), not an oversight.

## Module locality

When changing code in module X, prefer reading only `src/X/` and its direct dependencies (the layers below it).

If you find yourself reading 3+ unrelated modules to make a single local change, **stop and tell the user** — the module boundary is probably wrong, and that's worth fixing before continuing.

Layered architecture: **API → Logic → Services → Repositories → Models → Database.** Dependencies flow inward only. See [`src/README.md`](src/README.md) for the full overview.

## Commands

| Task | Command |
| --- | --- |
| Run tests | `dev test` |
| Run a single test file | `dev test path/to/test_file.py` |
| Lint | `dev lint` (black, isort, autoflake, title-case) |
| Start dev server | `dev dev up` |
| Stop dev server | `dev dev down` |
| Run migrations | `dev db migrate` |
| Reset database | `dev db reset` |

Pre-commit hooks run `dev lint` automatically — don't bypass with `--no-verify`.

## Where things live

- `src/api/routes/` — HTTP endpoints. Thin handlers; delegate to services.
- `src/services/` — Business logic. No HTTP, no SQL.
- `src/repositories/` — Data access. SQLAlchemy queries only.
- `src/models/` — SQLAlchemy models.
- `src/schemas/` — Pydantic request/response schemas.
- `src/logic/` — Cross-cutting processing (auth callbacks, user processing).
- `src/core/` — Config + Jinja templating utilities.
- `src/templates/` — Jinja2 + HTMX templates.
- `tests/` — Cross-module integration tests + shared fixtures (`conftest.py`). Unit tests live alongside source as `src/<module>/test_*.py`.

Each `src/<module>/` has its own `README.md` describing what the module does, what it doesn't do, and its tests. Read it before editing.

## Gotchas

- **Migrations before schema changes.** If you change a model, generate and run an Alembic migration before the model edit lands — otherwise startup fails.
- **fastapi-users tables.** The auth tables are managed by the `fastapi-users[sqlalchemy]` extension; don't redefine them in `models/`. Customizations go through `auth_config.py`.
- **Logging, not `print`.** Use the configured logger. There are still a few `print()` calls in `auth_config.py` — don't propagate that pattern.
- **Async everywhere.** Routes, services, and repositories are all async. Tests use `pytest-asyncio` (`asyncio_mode = "auto"`).
- **Templates use Starlette 1.0 API.** See commit `8f4b88d` if rendering breaks.

## When in doubt

- Read the module's own README first.
- Then read `src/README.md` for layer responsibilities.
- Then ask the user before reaching across many modules.
