# tests/contract/test_auth_routes_provider.py
import pytest
import os
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import logging
import time

# import socket # No longer needed here
# import multiprocessing # No longer needed here
from typing import Generator, Any

# from fastapi import FastAPI, Body, Response, status # No longer needed directly here
from pact import Verifier

# import uvicorn # No longer needed here
from yarl import URL  # Using yarl for URL manipulation

# Import shared constants and provider URLs from conftest
from tests.test_contract.conftest import (
    CONSUMER_NAME,
    PROVIDER_NAME,
    PACT_DIR,
    PACT_LOG_DIR,
    PROVIDER_URL,  # Import base URL
    PROVIDER_STATE_SETUP_URL,  # Import state setup URL
)

# Import the single handler dependency to mock
from app.logic.auth_processing import handle_registration

# Import the response schema for mock return value structure
from app.schemas.user import UserRead

# Get logger
log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO
)  # Use INFO level for less noise, DEBUG in conftest if needed

# --- Pact File Configuration ---
Pact_file_name = f"{CONSUMER_NAME.lower()}-{PROVIDER_NAME}.json"
Pact_file_path = os.path.join(PACT_DIR, Pact_file_name)

# --- Mock Configuration --- (No longer a fixture, just config)
dummy_user_data_config = {
    "id": str(uuid4()),  # Use string UUID for pickling if necessary
    "email": "test.user@example.com",
    "username": "testuser",
    "is_active": True,
    "is_superuser": False,
    "is_verified": False,
}

# --- Dependency Override Configuration for Parametrization ---
# Define the parametrization for the test function
# Pass picklable config: {target_path: config_for_mock}
provider_server_override_config = pytest.mark.parametrize(
    "provider_server",  # Target the provider_server fixture
    [
        {
            "app.logic.auth_processing.handle_registration": {  # Dependency path as key
                "return_value_config": dummy_user_data_config  # Picklable config
            }
        }
    ],
    indirect=True,  # Indicate this parameter indirectly parametrizes the provider_server fixture
    scope="module",
)


# --- Pact Verification Test ---
@provider_server_override_config  # Apply the parametrization marker to the test
def test_pact_verification_auth_routes(
    provider_server: URL,  # provider_server is now parametrized indirectly
    # mock_registration_handler: AsyncMock # Mock created in subprocess, no longer injected here
):
    """Verify the Auth Routes Pact contract against the running provider server.

    Relies on the provider_server fixture (parametrized indirectly) to start
    the server with the correct mock configuration created in the subprocess.
    """
    log.info(
        f"Test function execution: Verifying Pact for '{PROVIDER_NAME}' against {provider_server}"
    )

    if not os.path.exists(Pact_file_path):
        pytest.fail(f"Pact file not found: {Pact_file_path}. Run consumer test first.")

    log.info(f"Setting up verifier for provider '{PROVIDER_NAME}' at {provider_server}")
    log.info(f"Provider state setup URL: {PROVIDER_STATE_SETUP_URL}")

    verifier = Verifier(
        provider=PROVIDER_NAME,
        provider_base_url=str(provider_server),
        provider_states_setup_url=PROVIDER_STATE_SETUP_URL,
    )

    log.info("Running Verifier...")
    success, logs_dict = verifier.verify_pacts(Pact_file_path, log_dir=PACT_LOG_DIR)

    if success != 0:
        log.error("Pact verification failed. Logs:")
        try:
            import json

            print(json.dumps(logs_dict, indent=4))
        except ImportError:
            print(logs_dict)
        pytest.fail(f"Pact verification failed (exit code: {success}). Check logs.")
    else:
        log.info("Pact verification successful!")
