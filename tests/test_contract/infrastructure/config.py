"""Configuration constants for contract tests."""

import os

from yarl import URL

# Pact configuration
PACT_LOG_LEVEL = "warning"
PACT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "artifacts", "pacts")
)
PACT_LOG_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "artifacts", "logs")
)

# Provider server configuration
PROVIDER_HOST = "127.0.0.1"
PROVIDER_PORT = 8999
PROVIDER_BASE_URL = URL(f"http://{PROVIDER_HOST}:{PROVIDER_PORT}")
PROVIDER_STATE_SETUP_ENDPOINT_PATH = "_pact/provider_states"
PROVIDER_STATE_SETUP_FULL_URL = str(
    PROVIDER_BASE_URL / PROVIDER_STATE_SETUP_ENDPOINT_PATH
)

# Consumer server configuration
CONSUMER_HOST = "127.0.0.1"
CONSUMER_PORT = 8990
CONSUMER_BASE_URL = URL(f"http://{CONSUMER_HOST}:{CONSUMER_PORT}")

# Database configuration
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# Provider states the verifier may post during setup. Tests append more as they
# introduce new states.
KNOWN_PROVIDER_STATES = [
    "User test.user@example.com does not exist",
    "User 11111111-1111-1111-1111-111111111111 exists and is active",
    "Posts API accepts a create request",
]
