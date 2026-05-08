"""Root pytest configuration.

Loads `.env.test` (committed test defaults) into the process environment so
tests pass in fresh checkouts and worktrees without a personal `.env`. We
intentionally do NOT layer the developer's `.env` on top — `.env` typically
points at a real local Postgres for `dev up`, and tests must not run against
it. Shell env vars still win (`override=False`), so `DATABASE_URL=... dev
test` continues to work for one-off overrides.

The application itself still requires a personal `.env` for `dev up` etc. —
missing it is an intentional loud failure for non-test contexts.

Loads shared test fixtures from tests/fixtures.py as a pytest plugin so they
are available to tests anywhere in the repo — both colocated unit tests under
src/<module>/test_*.py and integration tests under tests/.
"""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env.test", override=False)

pytest_plugins = ["tests.fixtures"]
