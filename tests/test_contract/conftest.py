import pytest
import uvicorn
import time
import socket
import multiprocessing
import atexit  # Added for Pact cleanup
import os  # Added for path joining
from fastapi import FastAPI, Body, Response, status
from playwright.async_api import async_playwright
from app.api.routes import auth_pages
from pact import Consumer, Provider  # Added for Pact
import logging  # Add logging import
from yarl import URL  # Add URL import
from typing import Generator, Any, Callable, Dict  # Add necessary types
import importlib  # For dynamic imports
from app.logic.auth_processing import handle_registration
from unittest.mock import AsyncMock  # Import AsyncMock
from app.schemas.user import UserRead  # Import UserRead
import uuid

# Get the absolute route of the /pacts directory in this direcotry


# --- Pact Configuration ---
CONSUMER_NAME = "RegistrationUI"
PROVIDER_NAME = "backend-api"
PACT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "pacts"))
PACT_LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "log"))

# Ensure log and pact directories exist
os.makedirs(PACT_DIR, exist_ok=True)
os.makedirs(PACT_LOG_DIR, exist_ok=True)


# Define Pact Consumer and Provider
pact = Consumer(CONSUMER_NAME).has_pact_with(
    Provider(PROVIDER_NAME),
    pact_dir=PACT_DIR,
    log_dir=PACT_LOG_DIR,
)

# --- Provider State Handling (for Pact Verifier) ---
# NOTE: This relies on the mock being configured correctly by the
#       provider test fixture (`mock_registration_handler`) before verification runs.
#       If more complex state-dependent mocking is needed, this handler might
#       need access to the mock instance.
log_conftest = logging.getLogger(__name__)  # Use a distinct logger name

PROVIDER_STATE_SETUP_PATH = "_pact/provider_states"  # Define path constant
PROVIDER_HOST = "127.0.0.1"  # Keep fixed host/port for provider
PROVIDER_PORT = 8999
PROVIDER_URL = URL(f"http://{PROVIDER_HOST}:{PROVIDER_PORT}")
PROVIDER_STATE_SETUP_URL = str(PROVIDER_URL / PROVIDER_STATE_SETUP_PATH)


def provider_states_handler(state_info: dict = Body(...)):
    """Endpoint handler logic for provider state setup requests from Verifier."""
    state = state_info.get("state")
    log_conftest.info(f"Provider state setup endpoint called for state: '{state}'")
    if state == "User test.user@example.com does not exist":
        log_conftest.info(
            f"Acknowledging state (mock expected to be pre-configured): '{state}'"
        )
        pass
    else:
        log_conftest.warning(f"Unhandled provider state received: {state}")
    return Response(status_code=status.HTTP_200_OK)


def run_server(host: str, port: int):
    """Target function to run uvicorn in a separate process."""
    # Use the correct router for the consumer test app
    consumer_app = FastAPI(title="Consumer Test Server Process")
    consumer_app.include_router(auth_pages.router)
    uvicorn.run(consumer_app, host=host, port=port, log_level="warning")


def _find_available_port() -> int:
    """Finds an available port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def _start_server_process(host: str, port: int) -> multiprocessing.Process:
    """Starts the FastAPI server in a separate process."""
    server_process = multiprocessing.Process(
        target=run_server, args=(host, port), daemon=True
    )
    server_process.start()
    time.sleep(1)
    return server_process


def _terminate_server_process(process: multiprocessing.Process, origin: str):
    """Terminates the server process."""
    process.terminate()
    process.join(timeout=3)
    if process.is_alive():
        process.kill()


@pytest.fixture(scope="session")
def origin():
    """Pytest fixture to run the FastAPI app in a separate process."""
    host = "localhost"
    port = _find_available_port()
    origin = f"http://{host}:{port}"

    server_process = _start_server_process(host, port)

    yield origin

    _terminate_server_process(server_process, origin)


@pytest.fixture(scope="session")
async def browser():
    """Pytest fixture to launch a Playwright browser instance (headful)."""
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


@pytest.fixture(scope="session")
def pact_mock():
    """Provides the configured Pact instance to tests."""
    # The setup_pact_mock_server fixture ensures the service is running
    pact.start_service()
    print("Pact mock server started")
    yield pact
    pact.stop_service()
    print("Pact mock server stopped")


# --- Provider Server Fixtures ---


def _run_provider_server(
    host: str,
    port: int,
    state_path: str,
    state_handler: Callable,
    override_config: Dict[str, Dict] | None,
) -> None:
    """Target function to run the main FastAPI app with overrides for provider testing."""
    # Import necessary modules within the subprocess
    from app.main import app  # Import the main app instance
    from unittest.mock import AsyncMock
    from app.schemas.user import UserRead
    import importlib
    import uuid

    # No need to import router dynamically, we use the main app instance
    log_conftest.info(f"Using main app instance from app.main in PID {os.getpid()}")

    # Add the provider state setup endpoint *to the main app instance*
    app.post("/" + state_path)(state_handler)
    log_conftest.info(
        f"Added provider state handler at /{state_path} to main app instance"
    )

    # Apply dependency overrides based on config *to the main app instance*
    if override_config:
        for dep_path, mock_config in override_config.items():
            try:
                # Dynamically import the dependency to override
                dep_module_path, dep_name = dep_path.rsplit(".", 1)
                dep_module = importlib.import_module(dep_module_path)
                dependency_to_override = getattr(dep_module, dep_name)
                log_conftest.info(
                    f"Dynamically imported dependency '{dep_name}' from '{dep_module_path}'"
                )

                # Create mock instance based on config (simplified example)
                # TODO: Make mock creation more flexible based on mock_config dict
                if "return_value_config" in mock_config:
                    return_data = mock_config["return_value_config"]
                    # Convert ID back to UUID if needed by schema
                    if "id" in return_data:
                        try:
                            return_data["id"] = uuid.UUID(return_data["id"])
                        except (TypeError, ValueError):
                            log_conftest.warning(
                                f"Could not convert id '{return_data['id']}' to UUID, using string."
                            )
                            pass  # Keep as string if conversion fails

                    mock_instance = AsyncMock(return_value=UserRead(**return_data))
                    log_conftest.info(
                        f"Created AsyncMock for {dep_name} with return value: {return_data}"
                    )
                else:
                    mock_instance = AsyncMock()
                    log_conftest.info(f"Created default AsyncMock for {dep_name}")

                # Create factory function (lambda) in this scope
                mock_factory = lambda: mock_instance

                # Apply override
                app.dependency_overrides[dependency_to_override] = mock_factory
                log_conftest.info(f"Applied dependency override for {dep_name}")

            except (ImportError, AttributeError, ValueError, KeyError) as e:
                log_conftest.error(f"Failed to setup override for '{dep_path}': {e}")
                # Optionally raise SystemExit here too if override is critical
                # raise SystemExit(1)

    # Ensure overrides are cleared from the main app instance if the process exits unexpectedly?
    # This might be tricky. The fixture cleanup handles the process termination.

    log_conftest.info(
        f"Starting Uvicorn for provider server on {host}:{port} in PID {os.getpid()}"
    )
    uvicorn.run(app, host=host, port=port, log_level="debug")


@pytest.fixture(scope="module")
def provider_server(request) -> Generator[URL, Any, None]:
    """
    Starts the main FastAPI app IN a separate process for Pact verification.
    Dependency override configuration is passed via indirect parametrization.

    Yields:
        URL: The base URL of the running provider server.
    """
    log_conftest.info("Setting up provider server process fixture...")

    # Get dependency override config from indirect parametrization
    override_config = getattr(request, "param", None)
    if not (override_config and isinstance(override_config, dict)):
        override_config = None
        log_conftest.info("No valid dependency override config received.")
    else:
        log_conftest.info(f"Received override config: {list(override_config.keys())}")

    process_args = (
        PROVIDER_HOST,
        PROVIDER_PORT,
        PROVIDER_STATE_SETUP_PATH,
        provider_states_handler,
        override_config,
    )

    proc = multiprocessing.Process(
        target=_run_provider_server,
        args=process_args,
        daemon=True,
    )
    proc.start()
    log_conftest.info(
        f"Started provider server process (PID: {proc.pid}) on {PROVIDER_URL}"
    )

    time.sleep(2)  # Allow time for server startup
    if not proc.is_alive():
        proc.join(timeout=1)
        pytest.fail("Provider server process failed to start.", pytrace=False)

    yield PROVIDER_URL

    # Teardown
    log_conftest.info(f"Tearing down provider server process (PID: {proc.pid})...")
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=3)
    if proc.is_alive():
        log_conftest.warning(
            f"Server process {proc.pid} did not terminate gracefully. Killing."
        )
        proc.kill()
        proc.join(timeout=1)
    log_conftest.info("Provider server stopped.")
