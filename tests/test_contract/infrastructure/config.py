"""Configuration constants for contract tests."""

import os

# Pact configuration
PACT_LOG_LEVEL = "warning"
PACT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "artifacts", "pacts")
)
PACT_LOG_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "artifacts", "logs")
)

# Server hosts. Ports are allocated per session at runtime — see
# `infrastructure/ports.py` and the server fixtures in `conftest.py` — so
# concurrent contract sessions don't collide on a shared port.
PROVIDER_HOST = "127.0.0.1"
PROVIDER_STATE_SETUP_ENDPOINT_PATH = "_pact/provider_states"

CONSUMER_HOST = "127.0.0.1"

# Database configuration
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


# Provider states the verifier may post during setup. Derived from
# `tests.test_contract.manifest.CONTRACT_PAIRS`; new pairs append their
# state via the manifest, not here.
def _known_provider_states() -> list[str]:
    # Imported lazily because the manifest pulls in stub setup functions,
    # which transitively load `src.models` etc. — fine, just keeps this
    # module's import surface flat.
    from ..manifest import known_provider_states

    return known_provider_states()


KNOWN_PROVIDER_STATES: list[str] = _known_provider_states()
