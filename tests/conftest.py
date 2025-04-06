import os
import pytest
import asyncio
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine, text, Engine
# Remove Connection import, add Session and sessionmaker
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool
from alembic.config import Config
from alembic import command
from dotenv import load_dotenv
# Import the app's get_db dependency
from app.db import get_db
# Import Base for metadata access
from app.models import Base

# Load environment variables from .env file if it exists
load_dotenv()

# --- Database Fixtures ---

# Default Test DB URL (can be overridden by environment variable)
DEFAULT_TEST_DB_URL = "sqlite:///./test_chat_app.db"
TEST_DB_URL = os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DB_URL)

# Ensure we are using a test database URL
if "test" not in TEST_DB_URL:
    pytest.fail("TEST_DATABASE_URL does not seem to be a test database. Aborting tests.")

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


# NEW: Fixture for managing ORM Session with cleanup
@pytest.fixture(scope="function")
def db_session(test_engine_session: Engine):
    """Yields a SQLAlchemy ORM session with proper cleanup for each test."""
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine_session)
    session: Session = TestSessionLocal()
    print("\nDB Session created for test function")

    # --- Start Transaction --- (Optional but good practice for atomic setup)
    session.begin()

    try:
        yield session # Provide session to the test
        session.flush() # Ensure any pending changes within the test are flushed before cleanup
        session.commit() # Commit changes made *within* the test if needed (usually not)
    except Exception:
        print("\nRolling back session due to test error")
        session.rollback()
        raise # Re-raise the exception from the test
    finally:
        # --- Clean up Data --- (Crucial for isolation)
        print("\nCleaning up test data...")
        # Delete data from all tables managed by Base.metadata in reverse dependency order
        # This ensures foreign key constraints don't cause errors during delete
        for table in reversed(Base.metadata.sorted_tables):
            print(f"Deleting from {table.name}")
            session.execute(table.delete())
        session.commit() # Commit the deletions
        session.close() # Close the session
        print("\nDB Session cleanup complete and closed")


# --- Application Fixtures ---

@pytest.fixture(scope="function", autouse=True)
def override_db_url_for_tests(monkeypatch):
    """Ensure the app uses the TEST_DATABASE_URL during tests."""
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)


@pytest.fixture(scope="function")
def app_instance(db_session: Session): # Depends on db_session now!
    """Yield the FastAPI app instance with get_db overridden to use the test's session."""
    from app.main import app

    # Define the override for get_db
    def get_db_override():
        print(f"\nOverride get_db yielding session {db_session}")
        yield db_session # Yield the session provided by the db_session fixture
        print(f"\nOverride get_db finished for session {db_session}")

    app.dependency_overrides[get_db] = get_db_override
    print(f"\nApp get_db dependency overridden to use session {db_session}")

    yield app

    print("\nClearing app dependency overrides")
    app.dependency_overrides.clear()


# Updated test_client to depend on app_instance
@pytest_asyncio.fixture(scope="function")
async def test_client(app_instance):
    """Yield an httpx AsyncClient configured for the test app."""
    print("\nCreating test client")
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client 