# Tests: Shared fixtures, helpers, and cross-module tests

Most tests in this codebase are **colocated next to the source they cover** — e.g. `src/api/routes/test_auth_routes.py` lives next to `auth_routes.py`. This `tests/` directory holds the shared infrastructure that those colocated tests rely on, plus any cross-module integration tests.

## Why colocation

When the test file is in the same directory as the code, an agent (human or AI) editing the code is forced to encounter the test. That makes "update the tests" part of the natural editing flow rather than a separate step that gets forgotten.

See [`../CLAUDE.md`](../CLAUDE.md) for the full definition-of-done contract that makes test updates part of every code change.

## What lives here

- **`fixtures.py`** — shared pytest fixtures (`test_client`, `authenticated_client`, `db_test_session_manager`, `logged_in_user`, etc.). Loaded globally via `pytest_plugins = ["tests.fixtures"]` in the repo-root `conftest.py`, so colocated tests anywhere under `src/` can use them.
- **`helpers.py`** — non-fixture test utilities (e.g. `create_test_user(...)` for building User instances). Import as `from tests.helpers import create_test_user`.
- **`README.md`** — this file.
- **(future) cross-module integration tests** — tests that span multiple layers and don't have a single owning module belong here, not under `src/`.

## What does not live here

- **Unit tests for a specific module.** Those go next to the source: `src/<module>/test_*.py`.
- **Module-specific fixtures.** If a fixture is only useful for one module's tests, define it in a `conftest.py` next to that module's tests.

## Where the colocated tests are today

| Module | Tests |
| --- | --- |
| `src/api/routes/` | `test_auth_routes.py`, `test_users.py` |
| `src/services/` | none yet — gap |
| `src/repositories/` | none yet — gap |
| `src/logic/` | none yet — gap |
| `src/models/` | none yet — gap |

## Running tests

```bash
# All tests, anywhere in the repo
dev test

# Single colocated test file
dev test src/api/routes/test_auth_routes.py

# Match by keyword
dev test -k login

# Run only API-layer tests
dev test src/api/
```

`pytest` discovers `test_*.py` under both `tests/` and `src/` (configured via `testpaths = ["tests", "src"]` in `pyproject.toml`).

## How fixture discovery works

Pytest only auto-loads `conftest.py` from directories on the path between rootdir and a given test file. Because colocated tests under `src/` don't share a common parent with `tests/`, a `tests/conftest.py` would not reach them.

Solution: `tests/fixtures.py` is a **regular Python module** (not a conftest.py), and the **repo-root `conftest.py`** loads it as a pytest plugin:

```python
# conftest.py
pytest_plugins = ["tests.fixtures"]
```

Any fixture defined at module level in `tests/fixtures.py` is then available to every test in the repo.

## Adding a new test

1. **Find the module the code lives in.** If it's `src/services/foo_service.py`, the test goes at `src/services/test_foo_service.py`.
2. **Use the shared fixtures** by adding them as parameters: `async def test_x(test_client, authenticated_client, db_test_session_manager): ...`
3. **For helpers**, import from `tests.helpers`.
4. **For module-specific helpers**, define them in the test file itself, or in a sibling `conftest.py` if multiple test files in that module need them.

## Common testing patterns

### Database isolation

The `db_test_session_manager` fixture (in `tests/fixtures.py`) creates an in-memory SQLite database, runs `metadata.create_all()` before each test, and drops everything after. Each test starts with a clean schema.

### Authenticated requests

Use `authenticated_client` to make requests as a pre-created test user. Use `logged_in_user` to get the corresponding `User` ORM object.

```python
async def test_my_endpoint(authenticated_client, logged_in_user):
    response = await authenticated_client.get("/me")
    assert response.status_code == 200
    assert response.json()["id"] == str(logged_in_user.id)
```

### Creating extra users in a test

```python
from tests.helpers import create_test_user

async def test_with_extra_user(authenticated_client, db_test_session_manager):
    other = create_test_user(username="other-user")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    # ...
```

## Related documentation

- [`../CLAUDE.md`](../CLAUDE.md) — the doc/test/code coupling contract
- [`../src/README.md`](../src/README.md) — the architecture being tested
- Each module's `README.md` includes a "Tests" section pointing to its colocated test file
