# tests/contract/test_auth_routes_provider.py
import pytest
import os
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import logging

from fastapi import FastAPI
from pact import Verifier

from app.main import app  # Import the FastAPI app instance

# Import the single handler dependency to mock
from app.logic.auth_processing import handle_registration

# Import the response schema for mock return value structure
from app.schemas.user import UserRead

# --- Pact Configuration ---
PROVIDER_NAME = "backend-api"  # Must match consumer pact
PACT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "pacts")
# Assuming the consumer pact file is named this
PACT_FILE_AUTH = os.path.join(PACT_DIR, "frontend-pact-backend-api.json")
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
# --- Configuration End ---


@pytest.fixture(scope="module")
def app_override_auth_routes():
    """Overrides the registration handler dependency."""
    log.info("Setting up FastAPI app with override for Auth Handler Pact")

    # 1. Define the successful return structure (matching UserRead)
    #    This should align with the 'will_respond_with' body in the pact file.
    #    NOTE: The original pact used form-urlencoded, this mock assumes JSON response.
    #          The test WILL LIKELY FAIL until the consumer pact is updated.
    dummy_user_data = {
        "id": uuid4(),  # Example
        "email": "test.user@example.com",  # Match pact 'Like' or expected value
        "username": "testuser",  # Match pact 'Like' or expected value
        "is_active": True,
        "is_superuser": False,
        "is_verified": False,  # Default for new registration
    }
    # Use Pydantic model directly if handler returns it
    mock_handler_return_value = UserRead(**dummy_user_data)
    # Or use MagicMock if the handler returns an ORM object that FastAPI converts
    # mock_handler_return_value = MagicMock(spec=UserRead)
    # for k, v in dummy_user_data.items(): setattr(mock_handler_return_value, k, v)

    # 2. Create the AsyncMock for the handler function
    mock_handler = AsyncMock(return_value=mock_handler_return_value)

    # 3. Override the single dependency used by the route handler
    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[handle_registration] = lambda: mock_handler

    yield app  # Provide the modified app

    # 4. Cleanup
    log.info("Cleaning up FastAPI app override for Auth Handler")
    app.dependency_overrides = original_overrides


# --- Provider State Setup --- (Likely minimal for this simple case)
def provider_state_setup_auth_routes(state: str, **params):
    log.info(f"Setting up provider state for Auth Routes: '{state}'")
    if state == "User test.user@example.com does not exist":
        # The mock configured in the fixture already handles this success case.
        pass
    else:
        log.warning(f"Unhandled provider state: {state}")


# --- Pact Verification Test ---
def test_pact_verification_auth_routes(app_override_auth_routes: FastAPI):
    """Verify the Auth Routes Pact contract."""
    log.info(
        f"Starting Pact verification for '{PROVIDER_NAME}' auth routes using '{PACT_FILE_AUTH}'"
    )
    if not os.path.exists(PACT_FILE_AUTH):
        pytest.fail(f"Pact file not found: {PACT_FILE_AUTH}. Run consumer test first.")

    verifier = Verifier(
        provider=PROVIDER_NAME,
        provider_base_url="http://localhost",
        provider_app=app_override_auth_routes,  # Use the fixture with mocked handler
        pact_source=PACT_FILE_AUTH,
        provider_state_setup=provider_state_setup_auth_routes,
    )

    log.info("Running Verifier for Auth Routes...")
    # Add debug prints
    log.info(f"Verifier object type: {type(verifier)}")
    # log.info(f"Verifier dir: {dir(verifier)}") # This might be too verbose

    success, logs_dict = verifier.verify()

    if success != 0:
        log.error("Auth Routes Pact verification failed. Logs:")
        import json

        print(json.dumps(logs_dict, indent=4))
    assert success == 0, f"Pact verification failed (exit code: {success}). Check logs."

    log.info("Auth Routes Pact verification successful!")
