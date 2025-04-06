import os
import pytest
import asyncio
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
# Import Engine for type hint
from sqlalchemy import create_engine, text, Engine
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool # Use NullPool for testing to avoid shared connections
from alembic.config import Config
from alembic import command
from dotenv import load_dotenv
# Import the dependency function and the app's engine
from app.db import get_db, engine as app_engine

# Load environment variables from .env file if it exists
load_dotenv()

# --- Database Fixtures ---

# Default Test DB URL (can be overridden by environment variable)
DEFAULT_TEST_DB_URL = "sqlite:///./test_chat_app.db"
TEST_DB_URL = os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DB_URL)

# Ensure we are using a test database URL
if "test" not in TEST_DB_URL:
    pytest.fail("TEST_DATABASE_URL does not seem to be a test database. Aborting tests.")

# REMOVED global test_engine definition

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
    """Applies migrations at the start of the test session."""
    run_migrations()
    # No yield/cleanup needed here as it modifies the file state


# NEW: Session-scoped fixture for the test engine
@pytest.fixture(scope="session")
def test_engine_session() -> Engine:
    """Yields a SQLAlchemy engine configured for the test database."""
    print(f"\nCreating test engine for {TEST_DB_URL}")
    engine = create_engine(
        TEST_DB_URL,
        poolclass=NullPool,
        connect_args={"check_same_thread": False}
    )
    yield engine
    print("\nDisposing test engine")
    engine.dispose()


# Updated db_conn fixture: Manages the transaction for the test function
@pytest.fixture(scope="function")
def db_conn(test_engine_session: Engine):
    connection = test_engine_session.connect()
    transaction = connection.begin()
    print("\nDB Connection obtained and Transaction started for test function")
    try:
        yield connection  # Provide connection within transaction to the test
    finally:
        print("\nDB Transaction rolling back for test function")
        transaction.rollback()
        connection.close()


# Simpler override function: Just yields the connection
def override_get_db(connection: Connection):
    # This generator simply yields the connection passed to it
    print(f"\nOverride get_db yielding connection {connection}")
    yield connection
    print(f"\nOverride get_db finished for connection {connection}")


# --- Application Fixtures ---

@pytest.fixture(scope="function", autouse=True)
def override_db_url_for_tests(monkeypatch):
    """Ensure the app uses the TEST_DATABASE_URL during tests."""
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)


@pytest.fixture(scope="function")
def app_instance(db_conn: Connection): # Depends on db_conn now!
    """Yield the FastAPI app instance with get_db overridden to use the test's transaction connection."""
    from app.main import app

    # Define the override function inline for clarity, or keep separate
    # It needs to be a generator that yields the connection from db_conn
    def get_db_override():
        print(f"\nOverride get_db yielding connection {db_conn}")
        yield db_conn
        print(f"\nOverride get_db finished for connection {db_conn}")

    # Override get_db to use our generator that yields the db_conn connection
    app.dependency_overrides[get_db] = get_db_override
    print(f"\nApp get_db dependency overridden to use connection {db_conn} via generator")

    yield app

    # Clear overrides after test function finishes
    print("\nClearing app dependency overrides")
    app.dependency_overrides.clear()


# test_client now depends on app_instance, which depends on db_conn
@pytest_asyncio.fixture(scope="function")
async def test_client(app_instance):
    """Yield an httpx AsyncClient configured for the test app."""
    print("\nCreating test client")
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client 