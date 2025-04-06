import os
import pytest
import asyncio
from httpx import AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool # Use NullPool for testing to avoid shared connections
from alembic.config import Config
from alembic import command
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# --- Database Fixtures ---

# Default Test DB URL (can be overridden by environment variable)
DEFAULT_TEST_DB_URL = "sqlite:///./test_chat_app.db"
TEST_DB_URL = os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DB_URL)

# Ensure we are using a test database URL
if "test" not in TEST_DB_URL:
    pytest.fail("TEST_DATABASE_URL does not seem to be a test database. Aborting tests.")

# Create a separate engine for test setup/teardown if needed
# Using NullPool is important for testing frameworks
test_engine = create_engine(TEST_DB_URL, poolclass=NullPool)

# Alembic config for tests
alembic_cfg = Config("alembic.ini")
# Point alembic to the test database
alembic_cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)


def run_migrations():
    print(f"\nApplying migrations to test database: {TEST_DB_URL}")
    # Ensure the test DB file directory exists if using SQLite file DB
    db_path = TEST_DB_URL.split("///")[-1]
    if db_path != ":memory:":
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
        # Delete existing test DB file if it exists before migrating
        if os.path.exists(db_path):
            print(f"Deleting existing test database file: {db_path}")
            os.remove(db_path)

    command.upgrade(alembic_cfg, "head")
    print("Migrations applied.")


@pytest.fixture(scope="session", autouse=True)
def apply_migrations():
    """Applies migrations at the start of the test session and cleans up."""
    run_migrations()
    yield
    # Optional: Add cleanup here if needed, e.g., deleting the test db file
    # db_path = TEST_DB_URL.split("///")[-1]
    # if db_path != ":memory:" and os.path.exists(db_path):
    #     print(f"\nDeleting test database file after tests: {db_path}")
    #     os.remove(db_path)


# --- Application Fixtures ---

# This fixture is crucial: it overrides the DATABASE_URL used by the app during tests
@pytest.fixture(scope="session", autouse=True)
def override_db_url_for_tests(monkeypatch_session):
    """Ensure the app uses the TEST_DATABASE_URL during tests."""
    print(f"\nMonkeypatching app.db.DATABASE_URL to: {TEST_DB_URL}")
    monkeypatch_session.setenv("DATABASE_URL", TEST_DB_URL)
    # We also need to potentially reload the module if it already read the env var
    # Or better, ensure db module reads env var upon engine creation/function call
    # For now, setting the env var before app import should work if db.py uses getenv directly


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def app_instance():
    """Yield the FastAPI app instance."""
    # Import the app *after* the environment variable has been patched
    from app.main import app
    yield app


@pytest.fixture(scope="session")
async def test_client(app_instance):
    """Yield an httpx AsyncClient configured for the test app."""
    async with AsyncClient(app=app_instance, base_url="http://testserver") as client:
        print("\nTest client created.")
        yield client
        print("Test client closed.") 