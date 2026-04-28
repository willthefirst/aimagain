"""Root pytest configuration.

Loads shared test fixtures from tests/fixtures.py as a pytest plugin so they
are available to tests anywhere in the repo — both colocated unit tests under
src/<module>/test_*.py and integration tests under tests/.
"""

pytest_plugins = ["tests.fixtures"]
