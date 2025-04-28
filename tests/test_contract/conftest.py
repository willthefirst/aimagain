import pytest
import uvicorn
import time
import multiprocessing
import atexit
import os
from fastapi import FastAPI, Body, Response, status
from playwright.async_api import async_playwright
from app.api.routes import auth_pages
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

# Pact Configuration
CONSUMER_NAME = "RegistrationUI"
PROVIDER_NAME = "backend-api"
PACT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "pacts"))
PACT_LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "log"))

os.makedirs(PACT_DIR, exist_ok=True)
os.makedirs(PACT_LOG_DIR, exist_ok=True)

pact = Consumer(CONSUMER_NAME).has_pact_with(
    Provider(PROVIDER_NAME),
    pact_dir=PACT_DIR,
    log_dir=PACT_LOG_DIR,
)

# Provider State Handling & Server Config
log_provider = logging.getLogger("pact_provider_test")  # Renamed logger

PROVIDER_STATE_SETUP_PATH = "_pact/provider_states"
PROVIDER_HOST = "127.0.0.1"
PROVIDER_PORT = 8999
PROVIDER_URL = URL(f"http://{PROVIDER_HOST}:{PROVIDER_PORT}")
PROVIDER_STATE_SETUP_URL = str(PROVIDER_URL / PROVIDER_STATE_SETUP_PATH)


def provider_states_handler(state_info: dict = Body(...)):
    """Endpoint handler logic for provider state setup requests from Verifier."""
    state = state_info.get("state")
    if state != "User test.user@example.com does not exist":
        log_provider.warning(f"Unhandled provider state received: {state}")
    return Response(status_code=status.HTTP_200_OK)


# Consumer Test Server Config & Fixtures
CONSUMER_HOST = "127.0.0.1"
CONSUMER_PORT = 8990


def run_consumer_server_process(host: str, port: int):  # Renamed function
    """Target function to run consumer test server uvicorn in a separate process."""
    consumer_app = FastAPI(title="Consumer Test Server Process")
    consumer_app.include_router(auth_pages.router)
    uvicorn.run(consumer_app, host=host, port=port, log_level="warning")


def _start_consumer_server_process(
    host: str, port: int
) -> multiprocessing.Process:  # Renamed function
    """Starts the consumer test FastAPI server in a separate process."""  # Clarified docstring
    server_process = multiprocessing.Process(
        target=run_consumer_server_process,
        args=(host, port),
        daemon=True,  # Use renamed target
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
def origin() -> str:
    """Pytest fixture providing the origin URL for the running consumer test server."""
    host = CONSUMER_HOST
    port = CONSUMER_PORT
    origin_url = f"http://{host}:{port}"
    server_process = _start_consumer_server_process(host, port)  # Use renamed function
    yield origin_url
    _terminate_server_process(server_process)


# Playwright Fixtures
@pytest.fixture(scope="session")
async def browser():
    """Pytest fixture to launch a Playwright browser instance."""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        yield browser
        await browser.close()


@pytest.fixture(scope="function")
async def page(browser):
    """Pytest fixture to create a new browser page for each test."""
    page = await browser.new_page()
    yield page
    await page.close()


# Pact Consumer Fixture
@pytest.fixture(scope="session")
def pact_mock() -> Consumer:
    """Provides the configured Pact Consumer instance and manages its mock service."""
    try:
        pact.start_service()
        yield pact
    finally:
        pact.stop_service()


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

    # --- Database Setup for Provider Process --- REMOVED ---
    # from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    # from app.models import metadata  # Import the metadata
    # from app.db import get_db_session  # Import the dependency function
    # from typing import AsyncGenerator
    # TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"  # Use in-memory DB
    # provider_engine = create_async_engine(TEST_DATABASE_URL)
    # provider_session_maker = async_sessionmaker(provider_engine, expire_on_commit=False)
    # async def initialize_db():
    #     async with provider_engine.begin() as conn:
    #         await conn.run_sync(metadata.create_all)
    # asyncio.run(initialize_db())
    # async def override_get_db_session_provider() -> AsyncGenerator[AsyncSession, None]:
    #     async with provider_session_maker() as session:
    #         yield session
    # app.dependency_overrides[get_db_session] = override_get_db_session_provider
    # --- End Database Setup ---

    # Use the same logger name as the parent process for consistency
    log_provider_subprocess = logging.getLogger("pact_provider_test")

    app.post("/" + state_path)(state_handler)

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

    # --- Run Server with Patches Applied --- #
    try:
        # Apply all patches - REMOVED (MonkeyPatch applies immediately)
        # for patcher in patch_managers:
        #     patcher.start()

        # Run the Uvicorn server - monkeypatch keeps patches active
        uvicorn.run(app, host=host, port=port, log_level="debug")

    finally:
        # Stop all patches - MonkeyPatch handles undoing automatically
        # for patcher in reversed(patch_managers):
        #     try:
        #         patcher.stop()
        #     except RuntimeError as e:
        #         log_provider_subprocess.error(f"Error stopping patcher for {patcher.attribute}: {e}")

        # Explicitly undo patches applied by MonkeyPatch
        mp.undo()
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
