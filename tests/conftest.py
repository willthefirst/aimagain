import asyncio
from typing import AsyncGenerator, Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from fastapi import Depends

# REMOVED Depends import as it's not used in fixture overrides this way
# from fastapi import Depends

# Assuming your FastAPI app instance is in app.main
from app.main import app

# Updated dependency imports from app.db
from app.db import get_db_session, get_user_db
from app.models import User, metadata  # Assuming your models define metadata
from fastapi_users.db import SQLAlchemyUserDatabase

# Use an in-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL)
test_async_session_maker = async_sessionmaker(test_engine, expire_on_commit=False)


# Fixture to provide the asyncio event loop for tests
@pytest.fixture(scope="session")
def event_loop():
    # This is the default behavior, but explicit for clarity
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


# Master fixture to manage table creation/dropping and provide session maker
@pytest.fixture(scope="function")
async def db_test_session_manager() -> (
    AsyncGenerator[async_sessionmaker[AsyncSession], None]
):
    # Create tables before test runs
    async with test_engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    yield test_async_session_maker  # Provide the session maker to tests

    # Drop tables after test finishes
    async with test_engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)


# Override for the raw AsyncSession dependency
# Uses the globally defined test_async_session_maker
# Table lifecycle managed by db_test_session_manager fixture
async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_async_session_maker() as session:
        yield session


# Override for the FastAPI Users DB adapter dependency
async def override_get_user_db(
    # Depend on the *original* app dependency name.
    # FastAPI will provide the overridden version (override_get_db_session) here.
    session: AsyncSession = Depends(get_db_session),
) -> SQLAlchemyUserDatabase[User, Any]:
    yield SQLAlchemyUserDatabase(session, User)


# Fixture for the FastAPI app with overridden dependencies
@pytest.fixture(scope="function")
def test_app(
    # Explicitly depend on the manager fixture to ensure tables exist
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> FastAPI:
    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_user_db] = override_get_user_db
    yield app
    # Clean up overrides after test function finishes
    app.dependency_overrides.clear()


# Fixture for the async test client
@pytest.fixture(scope="function")
async def test_client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",  # Use test_app here
    ) as client:
        yield client
