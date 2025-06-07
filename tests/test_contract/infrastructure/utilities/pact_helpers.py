"""Pact-specific helper utilities."""

import atexit
import os

from pact import Consumer, Provider


def setup_pact(consumer_name: str, provider_name: str, port: int) -> Consumer:
    """Set up a Pact consumer with the given configuration."""
    from ..config import PACT_DIR, PACT_LOG_DIR

    os.makedirs(PACT_LOG_DIR, exist_ok=True)

    pact = Consumer(consumer_name).has_pact_with(
        Provider(provider_name), pact_dir=PACT_DIR, log_dir=PACT_LOG_DIR, port=port
    )

    pact.start_service()
    atexit.register(pact.stop_service)
    return pact
