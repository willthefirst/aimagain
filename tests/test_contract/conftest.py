import asyncio
import logging
import multiprocessing
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Dict, Generator
from unittest.mock import AsyncMock, patch

import pytest
import requests
import uvicorn
from fastapi import Body, FastAPI, Response, status
from pact import Consumer, Provider
from playwright.async_api import async_playwright
from requests.exceptions import ConnectionError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from yarl import URL

from app.api.routes import auth_pages, conversations
from app.db import get_db_session, get_user_db  # Import the dependency functions
from app.models import User, metadata  # Import User and metadata
from app.models.conversation import Conversation

# from app.repositories.conversation_repository import ConversationRepository # Not used directly here
from tests.test_contract.test_consumer_conversation_form import (
    PROVIDER_STATE_USER_ONLINE,
)

from .test_helpers import PACT_DIR

# Removed: from app.models import User - already imported

# --- Server Configuration ---
PACT_LOG_LEVEL = "warning"  # Or "debug" for more verbose pact logging

# Provider Server Configuration
PROVIDER_HOST = "127.0.0.1"
PROVIDER_PORT = 8999
PROVIDER_BASE_URL = URL(f"http://{PROVIDER_HOST}:{PROVIDER_PORT}")
PROVIDER_STATE_SETUP_ENDPOINT_PATH = "_pact/provider_states"
PROVIDER_STATE_SETUP_FULL_URL = str(
    PROVIDER_BASE_URL / PROVIDER_STATE_SETUP_ENDPOINT_PATH
)

# Consumer Test Server Configuration
CONSUMER_HOST = "127.0.0.1"
CONSUMER_PORT = 8990
CONSUMER_BASE_URL = URL(f"http://{CONSUMER_HOST}:{CONSUMER_PORT}")
# --- End Server Configuration ---

log_provider = logging.getLogger("pact_provider_test")

# REMOVED OLD DEFINITIONS:
# PROVIDER_STATE_SETUP_PATH = "_pact/provider_states"
# PROVIDER_URL = URL(f"http://{PROVIDER_HOST}:{PROVIDER_PORT}")
# PROVIDER_STATE_SETUP_URL = str(PROVIDER_URL / PROVIDER_STATE_SETUP_PATH)

# Database setup for provider server (in-memory SQLite)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# The actual engine and sessionmaker will be created within _run_provider_server_process
# to ensure they are in the correct process.

# import asyncio # Already imported
# from typing import AsyncGenerator, Any # Already imported
from collections.abc import (
    AsyncGenerator as AsyncGeneratorABC,  # Keep this distinct import
)
from contextlib import asynccontextmanager

from asyncstdlib import anext

# from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine # Already imported
from fastapi import Depends

# Imports for FastAPI Users, similar to test_api/conftest.py
from fastapi_users.db import SQLAlchemyUserDatabase

# import pytest # Already imported
# from fastapi import FastAPI # Already imported
from httpx import (  # AsyncClient not used directly here, but often part of test setups
    ASGITransport,
    AsyncClient,
)

# from app.models import User, metadata # User, metadata already imported
# from fastapi_users.db import SQLAlchemyUserDatabase # Already imported
# from app.schemas.user import UserCreate # Already imported and commented
from app.core.templating import templates
from app.main import app  # Assuming your FastAPI app instance is in app.main

# from app.schemas.user import UserCreate # Not used directly in this conftest for user creation logic

# below copied frog test_api/conftest.py, refactor so that we just reuse the same 'in memory test db'
# This section is being addressed by the current refactoring.





# from app.db import get_db_session, get_user_db # get_db_session already imported



def provider_states_handler(state_info: dict = Body(...)):
    """Endpoint handler logic for provider state setup requests from Verifier."""
    state = state_info.get("state")
    consumer = state_info.get(
        "consumer", "Unknown Consumer"
    )  # Get consumer if available

    log_provider.info(f"Received provider state '{state}' for consumer '{consumer}'")

    known_states = [
        "User test.user@example.com does not exist",
        PROVIDER_STATE_USER_ONLINE,
    ]

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


def _create_mock_user(email: str, username: str, user_id: uuid.UUID = None) -> User:
    """Helper function to create a mock User instance."""
    return User(
        id=user_id if user_id else uuid.uuid4(),
        email=email,
        username=username,
        is_active=True,
        # Add other required User fields if your User model has them (e.g., hashed_password)
        # hashed_password="mock_hashed_password", # Example: if needed by User model
        # is_superuser=False, # Example
        # is_verified=True,  # Example
    )


def _poll_server_ready(url: str, retries: int = 10, delay: float = 0.5) -> bool:
    """Polls a URL until it's responsive or retries are exhausted."""
    for i in range(retries):
        try:
            response = requests.get(url, timeout=1)
            if response.status_code == 200:
                log_provider.info(f"Server at {url} is ready.")
                return True
        except ConnectionError:
            log_provider.debug(
                f"Server at {url} not ready yet (attempt {i+1}/{retries}). Retrying in {delay}s..."
            )
        except requests.Timeout:
            log_provider.debug(
                f"Server at {url} timed out (attempt {i+1}/{retries}). Retrying in {delay}s..."
            )
        time.sleep(delay)
    log_provider.error(f"Server at {url} failed to start after {retries} retries.")
    return False


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

    # from app.models import User # No longer needed here, imported above
    # import uuid # No longer needed here, imported above

    consumer_app = FastAPI(title="Consumer Test Server Process")

    @consumer_app.get("/_health")
    async def health_check():
        return {"status": "ok"}

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
        mock_user = _create_mock_user(
            email="test@example.com", username="contract_test_user"
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
    # time.sleep(1) # Replaced with polling
    health_check_url = f"http://{host}:{port}/_health"
    if not _poll_server_ready(health_check_url):
        # If server fails to start, terminate the process and raise an error
        _terminate_server_process(server_process)
        raise RuntimeError(
            f"Consumer server process failed to start at {health_check_url}"
        )
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

    # host = CONSUMER_HOST # Use new config
    # port = CONSUMER_PORT # Use new config
    # origin_url = f"http://{host}:{port}" # Use new config
    origin_url = str(CONSUMER_BASE_URL)
    server_process = _start_consumer_server_process(
        CONSUMER_HOST, CONSUMER_PORT, routes_config, mock_auth
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


# --- Helper function for _run_provider_server_process ---
def _setup_provider_app_routes(
    app: FastAPI, state_path: str, state_handler: Callable, log: logging.Logger
):
    """Sets up health check and state handler routes for the provider app."""

    @app.get("/_health")
    async def health_check():
        return {"status": "ok"}

    log.info("Added /_health endpoint to provider app.")

    app.post("/" + state_path)(state_handler)
    log.info(f"Added state handler at /{state_path} to provider app.")


def _setup_provider_mock_auth(app: FastAPI, log: logging.Logger):
    """Sets up mock authentication for the provider app."""
    import uuid  # Keep import local if only used here for mock user id

    from app.auth_config import current_active_user
    from app.models import User  # Keep import local if only used here

    mock_user_instance = _create_mock_user(
        email="provider.mock@example.com",
        username="provider_mock_user",
        user_id=uuid.uuid4(),  # Ensure a unique ID for the mock provider user
    )

    async def get_mock_provider_user():
        return mock_user_instance

    app.dependency_overrides[current_active_user] = get_mock_provider_user
    log.info(f"Mocking current_active_user with user: {mock_user_instance.email}")
    return current_active_user  # Return the key for cleanup


def _apply_provider_patches(
    mp: pytest.MonkeyPatch, override_config: Dict[str, Dict], log: logging.Logger
):
    """Applies patches based on override_config using MonkeyPatch."""
    import uuid  # Keep import local for potential UUID conversion
    from unittest.mock import AsyncMock  # Keep import local

    if not override_config:
        return

    for patch_target_path, mock_config in override_config.items():
        try:
            if "return_value_config" in mock_config:
                return_data = mock_config["return_value_config"]
                if (
                    isinstance(return_data, dict)
                    and "id" in return_data
                    and isinstance(return_data["id"], str)
                ):
                    try:
                        # Attempt to convert string ID to UUID if it's a valid UUID string
                        uuid_obj = uuid.UUID(return_data["id"])
                        return_data["id"] = uuid_obj
                    except ValueError:
                        log.debug(
                            f"Could not convert id '{return_data['id']}' to UUID for {patch_target_path}. Using string."
                        )
                        pass  # Keep as string if not a valid UUID
                mock_instance = AsyncMock(return_value=return_data)
            else:
                mock_instance = AsyncMock()

            mp.setattr(patch_target_path, mock_instance)
            log.info(
                f"Applied patch for '{patch_target_path}' with mock: {mock_instance}"
            )
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            log.error(f"Failed to setup mock/patch for '{patch_target_path}': {e}")
            # MonkeyPatch handles its own undo, so direct mp.undo() here might be tricky
            # if part of a loop. Raising ensures the test process stops.
            raise RuntimeError(
                f"Failed to setup mock/patch for '{patch_target_path}'"
            ) from e


# --- End Helper functions ---


# Pact Provider Fixtures
def _run_provider_server_process(  # Renamed function
    host: str,
    port: int,
    state_path: str,
    state_handler: Callable,
    override_config: Dict[str, Dict] | None,
) -> None:
    """Target function to run the main FastAPI app with overrides for provider testing."""
    # Main app import is now global for the module
    # from app.main import app

    # SQLAlchemy engine and session for this process
    # These are created here to ensure they exist in this separate process
    provider_test_engine = create_async_engine(TEST_DATABASE_URL)
    provider_test_async_session_maker = async_sessionmaker(
        provider_test_engine, expire_on_commit=False
    )

    # Define local provider_override_get_db_session that captures provider_test_async_session_maker
    async def local_provider_override_get_db_session_impl() -> (
        AsyncGenerator[AsyncSession, None]
    ):
        async with provider_test_async_session_maker() as session:
            yield session

    # Define local provider_override_get_user_db
    async def local_provider_override_get_user_db_impl(
        # Depends on the overridden version of get_db_session
        session: AsyncSession = Depends(local_provider_override_get_db_session_impl),
    ) -> SQLAlchemyUserDatabase[User, Any]:
        yield SQLAlchemyUserDatabase(session, User)

    log_provider_subprocess = logging.getLogger(
        "pact_provider_test_subprocess"
    )  # Changed logger name slightly for clarity

    # Original dependency overrides from app instance
    original_dependency_overrides = app.dependency_overrides.copy()

    try:
        # Create tables
        async def create_db_tables():
            async with provider_test_engine.begin() as conn:
                await conn.run_sync(metadata.create_all)
            log_provider_subprocess.info(
                "In-memory DB tables created for provider test."
            )

        asyncio.run(create_db_tables())

        # Apply DB overrides
        app.dependency_overrides[get_db_session] = (
            local_provider_override_get_db_session_impl
        )
        app.dependency_overrides[get_user_db] = local_provider_override_get_user_db_impl
        log_provider_subprocess.info(
            "Applied DB dependency overrides for provider test."
        )

        _setup_provider_app_routes(
            app, state_path, state_handler, log_provider_subprocess
        )

        # Setup mock auth and keep track of the dependency key for cleanup
        # This might also need to be aware of the new override structure if it interacts with DB
        auth_dependency_key = _setup_provider_mock_auth(app, log_provider_subprocess)

        mp = pytest.MonkeyPatch()  # Keep monkeypatching as is for other overrides
        try:
            _apply_provider_patches(mp, override_config, log_provider_subprocess)

            uvicorn.run(app, host=host, port=port, log_level=PACT_LOG_LEVEL)

        finally:
            mp.undo()
            log_provider_subprocess.info(
                "MonkeyPatch.undo() called for provider patches."
            )
            # Note: uvicorn.run is blocking. Code here runs after server stops.

    finally:
        # This 'finally' block ensures cleanup even if uvicorn doesn't start or crashes early.

        # Drop tables
        async def drop_db_tables():
            async with provider_test_engine.begin() as conn:
                await conn.run_sync(metadata.drop_all)
            log_provider_subprocess.info(
                "In-memory DB tables dropped for provider test."
            )

        asyncio.run(drop_db_tables())

        # Restore original dependency overrides
        app.dependency_overrides = original_dependency_overrides
        log_provider_subprocess.info(
            "Restored original dependency overrides for provider app."
        )

        # The auth_dependency_key cleanup was inside the inner finally,
        # it should be robust enough, but ensure app.dependency_overrides is the correct one.
        # If _setup_provider_mock_auth modified the original_dependency_overrides copy, this is fine.
        # If it modified app.dependency_overrides directly, it's already handled by restoring.
        # For safety, let's ensure it's explicitly cleared from the live app.dependency_overrides
        # *before* restoring the original ones, or just rely on the full restoration.
        # The current logic in `_setup_provider_mock_auth` adds to app.dependency_overrides.
        # The restoration to original_dependency_overrides will inherently clear it if it was added.


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
        PROVIDER_STATE_SETUP_ENDPOINT_PATH,
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
    # time.sleep(2)
    health_check_url = f"{PROVIDER_BASE_URL}/_health"
    if not _poll_server_ready(health_check_url, retries=20, delay=0.5):
        _terminate_server_process(proc)
        pytest.fail("Provider server process failed to start.", pytrace=False)

    yield PROVIDER_BASE_URL

    _terminate_server_process(proc)


@pytest.fixture(scope="session", autouse=True)
def clean_pact_dir_before_session():
    """Ensures the pacts directory is clean before the test session starts."""
    if os.path.exists(PACT_DIR):
        shutil.rmtree(PACT_DIR)
    os.makedirs(PACT_DIR, exist_ok=True)
