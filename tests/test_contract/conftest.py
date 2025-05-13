from datetime import datetime, timezone
import pytest
import uvicorn
import time
import multiprocessing
import os
from fastapi import FastAPI, Body, Response, status
from playwright.async_api import async_playwright
from app.api.routes import auth_pages, conversations
from pact import Consumer, Provider
import logging
from yarl import URL
from typing import Generator, Any, Callable, Dict
import importlib
import uuid
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.models import metadata  # Import the metadata
from app.db import get_db_session  # Import the dependency function
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

# Import states from consumer test for clarity
from app.models.conversation import Conversation
from app.repositories.conversation_repository import ConversationRepository
from tests.test_contract.test_consumer_conversation_form import (
    PROVIDER_STATE_USER_ONLINE,
)

# Provider State Handling & Server Config
log_provider = logging.getLogger("pact_provider_test")  # Renamed logger

PROVIDER_STATE_SETUP_PATH = "_pact/provider_states"
PROVIDER_HOST = "127.0.0.1"
PROVIDER_PORT = 8999
PROVIDER_URL = URL(f"http://{PROVIDER_HOST}:{PROVIDER_PORT}")
PROVIDER_STATE_SETUP_URL = str(PROVIDER_URL / PROVIDER_STATE_SETUP_PATH)


# below copied frog test_api/conftest.py, refactor so that we just reuse the same 'in memory test db'

import asyncio
from typing import AsyncGenerator, Any
from collections.abc import AsyncGenerator as AsyncGeneratorABC
from contextlib import asynccontextmanager
from asyncstdlib import anext

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
from app.schemas.user import UserCreate  # Import UserCreate schema
from app.core.templating import templates  # Import the global templates object

# Use an in-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL)
test_async_session_maker = async_sessionmaker(test_engine, expire_on_commit=False)


# Master fixture to manage table creation/dropping and provide session maker
@pytest.fixture(scope="function")
async def db_test_session_manager() -> (
    AsyncGenerator[async_sessionmaker[AsyncSession], None]
):
    # Create tables before test runsa
    async with test_engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
        log_provider.info("Created tables")

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
    log_provider.info("Setting up user db overrides")
    yield SQLAlchemyUserDatabase(session, User)


# ^^^^^^^^^^^^^^^ copied frog test_api/conftest.py, refactor so that we just reuse the same 'in memory test db' ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^


def provider_states_handler(state_info: dict = Body(...)):
    """Endpoint handler logic for provider state setup requests from Verifier."""
    state = state_info.get("state")
    consumer = state_info.get(
        "consumer", "Unknown Consumer"
    )  # Get consumer if available

    log_provider.info(f"Received provider state '{state}' for consumer '{consumer}'")

    # List of known states this provider setup can handle (even if passively)
    known_states = ["User test.user@example.com does not exist"]

    if state in known_states:
        # Currently, the mocks are configured via test parametrization,
        # so the handler just needs to acknowledge the state is known.
        # In more complex scenarios, this is where you might set up DB state,
        # configure mocks dynamically, etc.
        log_provider.info(f"Acknowledged known provider state: {state}")
        return Response(status_code=status.HTTP_200_OK)
    else:
        # Log clearly if an unknown state is received
        log_provider.warning(f"Unhandled provider state received: {state}")
        # Optionally return an error, though Pact verification might proceed anyway
        # return Response(content=f"Unknown state: {state}", status_code=status.HTTP_400_BAD_REQUEST)
        # Returning OK allows verification to proceed, failures will happen at interaction level
        return Response(status_code=status.HTTP_200_OK)


# Consumer Test Server Config & Fixtures
CONSUMER_HOST = "127.0.0.1"
CONSUMER_PORT = 8990


def run_consumer_server_process(
    host: str, port: int, routes_config=None, mock_auth=True
):
    """Target function to run consumer test server uvicorn in a separate process.

    Args:
        host: Host address to bind to
        port: Port to bind to
        routes_config: Dict with keys as router modules and values as booleans to include/exclude
    """
    from app.auth_config import current_active_user
    from app.models import User
    import uuid

    consumer_app = FastAPI(title="Consumer Test Server Process")

    # Default configuration includes both routers
    if routes_config is None:
        routes_config = {
            "auth_pages": True,
            "conversations": True,
        }

    # Include routers based on configuration
    if routes_config.get("auth_pages", False):
        consumer_app.include_router(auth_pages.router)

    if routes_config.get("conversations", False):
        consumer_app.include_router(conversations.router)

    # Override authentication for contract tests
    if mock_auth:
        # Add log statement
        print
        log_provider.info("Adding mock auth for contract tests")
        # Create a mock user that will be used for all endpoints requiring auth
        mock_user = User(
            id=uuid.uuid4(),
            email="test@example.com",
            username="contract_test_user",
            is_active=True,
            # Add other required User fields as needed
        )

        async def get_mock_current_user():
            return mock_user

        # Override the dependency
        consumer_app.dependency_overrides[current_active_user] = get_mock_current_user

    uvicorn.run(consumer_app, host=host, port=port, log_level="warning")


def _start_consumer_server_process(
    host: str, port: int, routes_config=None, mock_auth=True
) -> multiprocessing.Process:
    """Starts the consumer test FastAPI server in a separate process."""
    server_process = multiprocessing.Process(
        target=run_consumer_server_process,
        args=(host, port, routes_config, mock_auth),
        daemon=True,
    )
    server_process.start()
    # TODO: Replace sleep with a proper readiness check
    time.sleep(1)
    return server_process


def _terminate_server_process(
    process: multiprocessing.Process,
):  # Removed unused origin arg
    """Terminates the server process."""
    process.terminate()
    process.join(timeout=3)
    if process.is_alive():
        # Use specific logger if available, otherwise print
        logger = logging.getLogger("test_server_termination")
        logger.warning(
            f"Server process {process.pid} did not terminate gracefully. Killing."
        )
        process.kill()
        process.join(timeout=1)  # Add join after kill


@pytest.fixture(scope="session")
def origin_with_routes(request) -> str:
    """Pytest fixture providing the origin URL for the running consumer test server
    with specified routes.

    Usage:
        @pytest.mark.parametrize("origin_with_routes", [{"auth_pages": True}], indirect=True)
        def test_auth_related(...):
            ...
    """
    routes_config = getattr(request, "param", None) or {
        "auth_pages": True,
        "conversations": True,
    }

    # Extract mock_auth from params or default to True
    mock_auth = True
    if isinstance(routes_config, dict) and "mock_auth" in routes_config:
        mock_auth = routes_config.pop("mock_auth")

    host = CONSUMER_HOST
    port = CONSUMER_PORT
    origin_url = f"http://{host}:{port}"
    server_process = _start_consumer_server_process(
        host, port, routes_config, mock_auth
    )
    yield origin_url
    _terminate_server_process(server_process)


# Playwright Fixtures
@pytest.fixture(scope="session")
async def browser():
    """Pytest fixture to launch a Playwright browser instance."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest.fixture(scope="function")
async def page(browser):
    """Pytest fixture to create a new browser page for each test."""
    page = await browser.new_page()
    yield page
    await page.close()


# Pact Provider Fixtures
def _run_provider_server_process(  # Renamed function
    host: str,
    port: int,
    state_path: str,
    state_handler: Callable,
    override_config: Dict[str, Dict] | None,
) -> None:
    """Target function to run the main FastAPI app with overrides for provider testing."""
    # Imports required only within the subprocess
    # import asyncio # No longer needed for DB setup
    from app.main import app
    from unittest.mock import AsyncMock, patch  # Import patch
    from app.schemas.user import UserRead
    import importlib
    import uuid
    import logging

    # --- Added imports for mock user ---
    from app.models import User  # Ensure this path is correct
    from app.auth_config import current_active_user  # Ensure this path is correct

    # --- End added imports ---

    # Use the same logger name as the parent process for consistency
    log_provider_subprocess = logging.getLogger("pact_provider_test")

    app.post("/" + state_path)(state_handler)

    # --- Mock Authentication Setup ---
    # Create a mock user that will be used for all endpoints requiring auth
    # This simulates an authenticated user for the provider tests.
    mock_user_instance = User(
        id=uuid.uuid4(),
        email="provider.mock@example.com",
        username="provider_mock_user",
        is_active=True,
        # Add other required User fields if your User model has them (e.g., hashed_password)
        # hashed_password="mock_hashed_password", # Example: if needed by User model
        # is_superuser=False, # Example
        # is_verified=True,  # Example
    )

    async def get_mock_provider_user():
        return mock_user_instance

    # Override the dependency for current_active_user
    # This ensures that endpoints protected by current_active_user will receive the mock_user_instance
    app.dependency_overrides[current_active_user] = get_mock_provider_user
    log_provider_subprocess.info(
        f"Mocking current_active_user with user: {mock_user_instance.email}"
    )
    # --- End Mock Authentication Setup ---

    # todo
    # logger
    log_provider_subprocess.info("Setting up db session and user db overrides")
    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_user_db] = override_get_user_db

    # Context manager for patches - REMOVED
    # patch_managers = [] # Use a list to manage multiple patches if needed

    # Use pytest's MonkeyPatch utility for managing patches
    mp = pytest.MonkeyPatch()

    if override_config:
        for patch_target_path, mock_config in override_config.items():
            try:
                # --- Create the AsyncMock --- #
                if "return_value_config" in mock_config:
                    return_data = mock_config["return_value_config"]
                    if "id" in return_data:
                        try:
                            return_data["id"] = uuid.UUID(return_data["id"])
                        except (TypeError, ValueError):
                            pass  # Ignore conversion error, use string ID
                    mock_instance = AsyncMock(return_value=UserRead(**return_data))
                else:
                    mock_instance = AsyncMock()
                # --- End Create the AsyncMock --- #

                # --- Setup Patch using MonkeyPatch --- #
                # Instead of unittest.mock.patch, use mp.setattr
                mp.setattr(patch_target_path, mock_instance)
                # --- End Setup Patch --- #

            except (
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
            ) as e:  # Added AttributeError
                log_provider_subprocess.error(
                    f"Failed to setup mock/patch for '{patch_target_path}': {e}"
                )
                # Clean up any patches potentially applied before the error
                mp.undo()
                raise RuntimeError(
                    f"Failed to setup mock/patch for '{patch_target_path}'"
                ) from e

    # Create DB tables before starting the server
    # This ensures that the database schema is available for the provider app process
    async def create_tables_for_provider():
        async with test_engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

        log_provider_subprocess.info(
            "Database tables created for provider server process."
        )

        # TODO: make this only applicable to the tests that depends on it with provider states

        async with test_async_session_maker() as session:
            async with session.begin():
                conv_repo = ConversationRepository(session=session)

                creator_user = User(
                    id=uuid.uuid4(),
                    email="creator.mock@example.com",
                    username="creator_mock_user",
                    is_active=True,
                )

                invitee_user = User(
                    id=uuid.uuid4(),
                    email="invitee.mock@example.com",
                    username="invitee_mock_user",
                    is_active=True,
                )

                initial_message_content = "Hello, world!"
                now = datetime.now(timezone.utc)

                new_conversation = Conversation(
                    slug="mock-slug",
                    created_by_user_id=creator_user.id,
                    last_activity_at=now,
                )
                session.add(new_conversation)
                session.add(creator_user)
                await session.flush()

    asyncio.run(create_tables_for_provider())

    # --- Run Server with Patches Applied --- #
    try:
        # Run the Uvicorn server - monkeypatch keeps patches active
        uvicorn.run(app, host=host, port=port, log_level="debug")

    finally:
        # Drop DB tables after the server stops
        # This cleans up the database state for the provider app process
        async def drop_tables_for_provider():
            async with test_engine.begin() as conn:
                await conn.run_sync(metadata.drop_all)
            log_provider_subprocess.info(
                "Database tables dropped for provider server process."
            )

        try:
            asyncio.run(drop_tables_for_provider())
        except Exception as e:
            log_provider_subprocess.error(
                f"Error dropping tables for provider server process: {e}"
            )

        # Explicitly undo patches applied by MonkeyPatch
        mp.undo()
        # --- Clear dependency override ---
        if current_active_user in app.dependency_overrides:
            del app.dependency_overrides[current_active_user]
            log_provider_subprocess.info("Cleared mock current_active_user override.")
        # --- End Clear dependency override ---
    # --- End Run Server --- #


@pytest.fixture(scope="module")
def provider_server(request) -> Generator[URL, Any, None]:
    """
    Starts the main FastAPI app in a separate process for Pact verification.
    Dependency override/patching configuration is passed via indirect parametrization.
    """
    override_config = getattr(request, "param", None)
    if not (override_config and isinstance(override_config, dict)):
        override_config = None

    process_args = (
        PROVIDER_HOST,
        PROVIDER_PORT,
        PROVIDER_STATE_SETUP_PATH,
        provider_states_handler,
        override_config,
    )

    proc = multiprocessing.Process(
        target=_run_provider_server_process,  # Use renamed target
        args=process_args,
        daemon=True,
    )
    proc.start()

    # TODO: Replace sleep with a proper readiness check (e.g., polling an endpoint)
    time.sleep(2)
    if not proc.is_alive():
        proc.join(timeout=1)
        # No longer need to clear app.dependency_overrides here
        # from app.main import app
        # app.dependency_overrides.clear()
        pytest.fail("Provider server process failed to start.", pytrace=False)

    yield PROVIDER_URL

    _terminate_server_process(proc)
    # No longer need to clear app.dependency_overrides here
    # from app.main import app
    # app.dependency_overrides.clear()
