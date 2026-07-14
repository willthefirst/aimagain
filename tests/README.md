# Tests

Most tests are **colocated** next to the source they cover (`src/domain/routes/auth/test_auth_routes.py` lives next to `auth_routes.py`). This directory holds the shared infrastructure those colocated tests depend on, plus the documented cross-layer exception (contract tests).

Colocation puts the test in front of any agent editing the code. See [`../CLAUDE.md`](../CLAUDE.md) for the definition-of-done that makes test updates part of every code change.

## What lives here

- `fixtures.py` — shared pytest fixtures (`test_client`, `authenticated_client`, `db_test_session_manager`, `logged_in_user`, ...). Loaded globally via `pytest_plugins = ["tests.fixtures"]` in the repo-root `conftest.py`, so colocated tests anywhere under `src/` see them.
- `helpers.py` — non-fixture utilities: `create_test_user`, `promote_to_admin`, per-kind post factories (`referral_payload`, `opening_payload`, `make_referral_detail`, `make_opening_detail`). Factories supply spec-required defaults so tests only override the fields they're asserting on; defaults sit next to the factory functions so updating spec defaults is a one-place change.
- `test_contract/` — Pact contract tests for HTML form ↔ API endpoint pairs. See [`test_contract/README.md`](test_contract/README.md).

Module-specific fixtures go in a `conftest.py` next to that module's tests, not here.

## Fixture discovery

Pytest only auto-loads `conftest.py` from directories on the path between rootdir and a given test file, so a `tests/conftest.py` wouldn't reach colocated tests under `src/`. Instead, `tests/fixtures.py` is a regular module loaded by the repo-root `conftest.py` as `pytest_plugins = ["tests.fixtures"]`.

## Running

```bash
dev test                                              # everything (excludes contract — see below)
dev test src/domain/routes/auth/test_auth_routes.py        # single file
dev test -k login                                     # by keyword
dev test tests/test_contract                          # explicit opt-in for contract
```

`pytest` discovers `test_*.py` under both `tests/` and `src/` (configured via `testpaths` in `pyproject.toml`). Contract tests are excluded from the default run — see [`test_contract/README.md`](test_contract/README.md).

## Auth fixture caching

`authenticated_client` and `superuser_client` share a session-cached Argon2 password hash and JWT cookie. Each fixture uses a fixed user UUID (`TESTUSER_ID`, `SUPERUSER_ID`) so the JWT is identical across tests — `JWTStrategy.write_token` only reads `user.id`. Per test, the fixture inserts a verified user row directly with the cached hash and attaches the cached cookie; no `/auth/jwt/login` round-trip, no per-test Argon2 hash or verify.

Tests that exercise the real login endpoint (`POST /auth/jwt/login`) still do so explicitly — see `src/domain/routes/auth/test_auth_routes.py::test_login_success`. The cached fixture keeps every *other* test from paying Argon2's cost on the way to its own assertion.

## Database isolation

`db_test_session_manager` creates an in-memory SQLite database, runs `metadata.create_all()` before each test, and drops everything after. The test engine registers a `connect` listener that runs `PRAGMA foreign_keys = ON` on every new SQLite connection — same as the production engine in [`../src/db.py`](../src/db.py). Without it, `ON DELETE CASCADE` / `ON DELETE SET NULL` are defined but silently un-enforced, and FK-dependent tests would pass for the wrong reason.

## Template-test selectors

Selectors MUST scope to a stable handle on the region under test (an `id`, `class`, `data-testid`, or a semantic landmark like `nav[aria-label="Primary"]`) — e.g. `#user-list > li`. Do not rely on a page having only one `<ul>` / `<form>` / `<table>`; that property is incidental and breaks the first time anything list-shaped lands in a shared template. When adding markup to `base.html` or a shared template, give the new element a stable handle too. Exclusion selectors (`ul:not([aria-label="Primary"]) > li`) are a smell — prefer inclusion.

## Testing scripts under `scripts/dev/`

`scripts/` and `scripts/dev/` are regular Python packages (each has an `__init__.py`), so tests import script modules via `from scripts.dev import ...` rather than `importlib.util.spec_from_file_location`. Scripts remain runnable as standalone files.
