"""Configuration constants for contract tests."""

import os

from yarl import URL

# Pact configuration
PACT_LOG_LEVEL = "warning"
PACT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "artifacts", "pacts"))

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

# Known provider states
KNOWN_PROVIDER_STATES = [
    "User test.user@example.com does not exist",
    "user has pending invitations",
    # Add more states as needed
]

PACT_LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "artifacts", "logs"))
