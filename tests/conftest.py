import os
import pytest
import pytest_asyncio
from typing import AsyncGenerator, Generator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
import asyncio
import logging # Added for better logging

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Import your FastAPI app and base model metadata
from app.main import app as fastapi_app # Assuming your FastAPI app instance is named 'app' in 'app.main'
from app.models import metadata # Import your Base model metadata
from app.db import get_db # Import the original dependency getter

# Use a file-based SQLite database for testing to ensure persistence
# across connections within the same test session.
TEST_DB_PATH = "./test.db"
TEST_DATABASE_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"

# Create the test database engine
# NullPool is recommended for testing with SQLite
test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)

# Create a sessionmaker for the test database
TestingSessionLocal = async_sessionmaker(
    autocommit=False, autoflush=False, bind=test_engine
)

# --- Fixtures ---

@pytest.fixture(scope="session", autouse=True)
async def setup_database():
    """
    Fixture to create database tables before tests run and drop/delete them afterwards.
    Runs once per session. Made autouse=True to ensure it runs.
    Uses a file-based DB (test.db).
    """
    # Ensure the old DB file is removed before starting, if it exists
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    async with test_engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield
    # Optional: Drop tables if needed, though removing the file is usually sufficient
    # async with test_engine.begin() as conn:
    #     await conn.run_sync(metadata.drop_all)

    # Explicitly dispose of the engine to release file handles before deleting
    await test_engine.dispose()

    # Remove the test database file
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Provides a database session for each test function, managed by the sessionmaker.
    Connects to the file-based test DB.
    """
    async with TestingSessionLocal() as session:
        log.debug("DB session provided by fixture.")
        yield session
        log.debug("DB session closed.")

@pytest.fixture(scope="function") # Changed scope to function to match db_session
def app(setup_database, db_session: AsyncSession) -> Generator: # Inject db_session
    """
    Fixture to override the database dependency in the FastAPI app
    to use the test-specific session.
    """
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        """Dependency override for get_db, yields the test's db_session."""
        log.debug("Override get_db yielding test session.")
        yield db_session # Yield the session from the db_session fixture

    fastapi_app.dependency_overrides[get_db] = override_get_db
    yield fastapi_app
    # Clean up overrides after test function finishes
    fastapi_app.dependency_overrides.clear()

@pytest_asyncio.fixture(scope="function")
async def test_client(app) -> AsyncGenerator[AsyncClient, None]:
    """
    Provides an HTTPX AsyncClient for making requests to the test app.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
