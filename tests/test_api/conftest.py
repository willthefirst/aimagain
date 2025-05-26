from typing import Any, AsyncGenerator

import pytest
from asyncstdlib import anext
from fastapi import Depends, FastAPI
from fastapi_users.db import SQLAlchemyUserDatabase
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.templating import templates  # Import the global templates object

# Updated dependency imports from app.db
from app.db import get_db_session, get_user_db

# Assuming your FastAPI app instance is in app.main
from app.main import app
from app.models import User, metadata  # Assuming your models define metadata
from app.schemas.user import UserCreate  # Import UserCreate schema

# REMOVED Depends import as it's not used in fixture overrides this way
# from fastapi import Depends


# Use an in-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL)
test_async_session_maker = async_sessionmaker(test_engine, expire_on_commit=False)


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

    # Add the app instance to Jinja globals so url_for can find it
    original_app_global = templates.env.globals.get("app")
    templates.env.globals["app"] = app

    yield app
    # Clean up overrides after test function finishes
    app.dependency_overrides.clear()
    # Restore or remove the global modification
    if original_app_global is not None:
        templates.env.globals["app"] = original_app_global
    elif "app" in templates.env.globals:
        del templates.env.globals["app"]


# Fixture for the async test client
@pytest.fixture(scope="function")
async def test_client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",  # Use test_app here
    ) as client:
        yield client


# Helper function to create a user (not a fixture itself)
async def create_test_user(
    session_maker: async_sessionmaker[AsyncSession],
    user_data: UserCreate,
    user_manager_dependency: Any,  # Accept the user manager dependency
) -> User:
    async with session_maker() as session:
        # Need to handle async generator dependency correctly
        user_manager_gen = user_manager_dependency(
            SQLAlchemyUserDatabase(session, User)
        )
        user_manager = await anext(user_manager_gen)  # Get the manager instance
        try:
            user = await user_manager.create(user_data)
            await session.commit()
            await session.refresh(user)
            # Ensure user is fully loaded before returning
            return user
        finally:
            # Ensure the generator is closed properly
            try:
                # Consume the rest of the generator to clean up
                await anext(user_manager_gen)
            except StopAsyncIteration:
                pass
            # Explicitly close if it has an aclose method (good practice)
            if hasattr(user_manager_gen, "aclose"):
                await user_manager_gen.aclose()


# Fixture to provide an authenticated client
@pytest.fixture(scope="function")
async def authenticated_client(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    test_app: FastAPI,  # Need the app to get the dependency
) -> AsyncGenerator[AsyncClient, None]:
    from app.auth_config import get_user_manager  # New import

    user_data = UserCreate(
        email="testuser@example.com",
        password="password123",
        username="testuser",  # Add username if required by your UserCreate
    )
    # Get the actual dependency function from the app
    user_manager_dependency = test_app.dependency_overrides.get(
        get_user_db, get_user_db
    )

    # Create the user directly using the user manager logic
    # We need a session to create the user manager
    await create_test_user(db_test_session_manager, user_data, get_user_manager)

    # Log the user in
    login_data = {
        "username": user_data.email,  # fastapi-users uses email as username for login
        "password": user_data.password,
    }
    res = await test_client.post("/auth/jwt/login", data=login_data)

    # Get the cookie from the response
    cookie = res.headers["Set-Cookie"]
    # Extract the token from the cookie
    access_token = cookie.split(";")[0].split("=")[1]

    # Set the cookie header for the client
    test_client.headers["Cookie"] = f"fastapiusersauth={access_token}"

    yield test_client

    # Clean up: remove the header after the test
    del test_client.headers["Cookie"]

    # Optional: Delete the user after test if needed, though DB drop handles it
    # async with db_test_session_manager() as session:
    #     await session.delete(user)
    #     await session.commit()


# Fixture to provide the User object corresponding to the authenticated client
@pytest.fixture(scope="function")
async def logged_in_user(
    authenticated_client: AsyncClient,  # Ensure this runs after auth client is set up
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> User:
    """Provides the User object for the default authenticated user."""
    # The user was created in authenticated_client fixture
    # Fetch the user from the DB based on the known test email
    async with db_test_session_manager() as session:
        from app.repositories.user_repository import UserRepository

        user_repo = UserRepository(session)
        user = await user_repo.get_user_by_email("testuser@example.com")
        if not user:
            pytest.fail(
                "Test user 'testuser@example.com' not found in DB for logged_in_user fixture"
            )
        return user
