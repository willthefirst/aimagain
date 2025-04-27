# tests/contract/test_auth_routes_provider.py
import pytest
import os
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import logging
import time
import socket
import multiprocessing
from typing import Generator, Any

from fastapi import FastAPI, Body, Response, status
from pact import Verifier
import uvicorn
from yarl import URL  # Using yarl for URL manipulation

from app.main import app  # Import the main FastAPI app instance

# Import the single handler dependency to mock
from app.logic.auth_processing import handle_registration

# Import the response schema for mock return value structure
from app.schemas.user import UserRead


# --- Test Server Configuration ---
def _find_available_port() -> int:
    # Temporarily disable dynamic port finding for debugging
    # with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    #     s.bind(("127.0.0.1", 0))
    #     return s.getsockname()[1]
    return 8999


# Define host, find port, create URL
PROVIDER_HOST = "127.0.0.1"
PROVIDER_PORT = 8999  # Use fixed port
PROVIDER_URL = URL(f"http://{PROVIDER_HOST}:{PROVIDER_PORT}")
PROVIDER_STATE_SETUP_PATH = "_pact/provider_states"
PROVIDER_STATE_SETUP_URL = str(PROVIDER_URL / PROVIDER_STATE_SETUP_PATH)


# --- Pact Configuration ---
PROVIDER_NAME = "backend-api"  # Must match consumer pact
PACT_DIR = os.path.join(os.path.dirname(__file__), "pacts")
PACT_FILE_AUTH = os.path.join(PACT_DIR, "registrationui-backend-api.json")
logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)
# --- Configuration End ---


# --- Mock Handler Setup ---
# We define the mock return value globally or within the fixture setup
dummy_user_data = {
    "id": uuid4(),
    "email": "test.user@example.com",
    "username": "testuser",
    "is_active": True,
    "is_superuser": False,
    "is_verified": False,
}
mock_handler_return_value = UserRead(**dummy_user_data)
mock_handler = AsyncMock(return_value=mock_handler_return_value)


# --- Provider State Handling ---
# This endpoint will be added to the app temporarily by the fixture
# to handle callbacks from the Pact Verifier.
@app.post("/" + PROVIDER_STATE_SETUP_PATH)
def provider_states_handler(state_info: dict = Body(...)):
    """Endpoint to handle provider state setup requests from Verifier."""
    state = state_info.get("state")
    log.info(f"Provider state setup endpoint called for state: '{state}'")
    # In a more complex scenario, you might adjust mocks or DB state here
    # based on the 'state' value. For this test, the mock is pre-configured.
    if state == "User test.user@example.com does not exist":
        # Ensure the mock is configured for success (already done globally)
        mock_handler.reset_mock()  # Reset call counts etc.
        mock_handler.return_value = mock_handler_return_value  # Re-assign return value
        mock_handler.side_effect = None  # Ensure no exception is set
        log.info(f"Configured mock for state: '{state}'")
    else:
        log.warning(f"Unhandled provider state received: {state}")
        # Optionally raise an error for unhandled states
        # return Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)

    return Response(status_code=status.HTTP_200_OK)


# --- Test Server Management ---
def run_server() -> None:
    """Target for multiprocessing.Process to run the app."""
    print("Running in heeeeayserver...")
    # Ensure run_server also uses the fixed port directly if logic changes later
    uvicorn.run(app, host=PROVIDER_HOST, port=PROVIDER_PORT, log_level="debug")


@pytest.fixture(scope="module")
def provider_server() -> Generator[URL, Any, None]:
    """
    Fixture to:
    1. Override the handle_registration dependency in the main app.
    2. Start the FastAPI app (with override) in a separate process.
    3. Yield the base URL of the running test server.
    4. Terminate the server and clean up the override on teardown.
    """
    log.info("Setting up provider server fixture...")

    # 1. Override dependency BEFORE starting server process
    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[handle_registration] = lambda: mock_handler
    log.info(f"Overrode handle_registration dependency.")

    # 2. Start server process
    proc = multiprocessing.Process(target=run_server, daemon=True)
    proc.start()
    log.info(f"Started provider server process (PID: {proc.pid}) on {PROVIDER_URL}")
    time.sleep(2)  # Allow time for server to start
    if not proc.is_alive():
        pytest.fail("Provider server process failed to start.", pytrace=False)

    # 3. Yield the URL
    yield PROVIDER_URL

    # 4. Teardown: Terminate server and restore overrides
    log.info(f"Tearing down provider server fixture (PID: {proc.pid})...")
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=3)
    if proc.is_alive():
        log.warning(f"Server process {proc.pid} did not terminate gracefully. Killing.")
        proc.kill()
        proc.join(timeout=1)
    app.dependency_overrides = original_overrides
    log.info("Provider server stopped and dependency overrides restored.")


# --- Pact Verification Test ---
def test_pact_verification_auth_routes(provider_server: URL):  # Use the server fixture
    """Verify the Auth Routes Pact contract against the running provider server."""
    log.info(
        f"Starting Pact verification for '{PROVIDER_NAME}' auth routes using '{PACT_FILE_AUTH}'"
    )
    if not os.path.exists(PACT_FILE_AUTH):
        pytest.fail(f"Pact file not found: {PACT_FILE_AUTH}. Run consumer test first.")

    log.info(f"Setting up verifier with {PROVIDER_NAME} at {provider_server}")
    # Initialize Verifier pointing to the running test server
    verifier = Verifier(
        provider=PROVIDER_NAME,
        provider_base_url=str(provider_server),  # URL from the fixture
        provider_states_setup_url=PROVIDER_STATE_SETUP_URL,  # Callback URL for states
        # We don't need provider_app here
    )

    log.info("Running Verifier for Auth Routes...")
    # Pass the pact file path(s) directly to verify_pacts()
    success, logs_dict = verifier.verify_pacts(PACT_FILE_AUTH)

    # Assertion remains the same
    if success != 0:
        log.error("Auth Routes Pact verification failed. Logs:")
        import json

        print(json.dumps(logs_dict, indent=4))  # Print logs for debugging
    assert success == 0, f"Pact verification failed (exit code: {success}). Check logs."

    log.info("Auth Routes Pact verification successful!")


# Remove the old fixture if it exists (it was implicitly removed by replacing the file content)
# @pytest.fixture(scope="module")
# def app_override_auth_routes(): ...
