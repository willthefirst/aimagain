"""Root pytest configuration.

Loads `.env.test` (committed test defaults) into the process environment so
tests pass in fresh checkouts and worktrees without a personal `.env`. The
application itself still requires a personal `.env` for `dev up` etc. —
missing it is an intentional loud failure for non-test contexts.

Loads shared test fixtures from tests/fixtures.py as a pytest plugin so they
are available to tests anywhere in the repo — both colocated unit tests under
src/<module>/test_*.py and integration tests under tests/.
"""

from pathlib import Path

from dotenv import load_dotenv

_repo_root = Path(__file__).resolve().parent
load_dotenv(_repo_root / ".env.test", override=False)
load_dotenv(_repo_root / ".env", override=True)

pytest_plugins = ["tests.fixtures"]
