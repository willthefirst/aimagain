import atexit
import os
from pact import Consumer, Provider
from typing import Generator

PACT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "pacts"))
PACT_LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "log"))


def setup_pact(
    consumer_name: str, provider_name: str
) -> Generator[Consumer, None, None]:
    os.makedirs(PACT_DIR, exist_ok=True)
    os.makedirs(PACT_LOG_DIR, exist_ok=True)

    pact = Consumer(consumer_name).has_pact_with(
        Provider(provider_name),
        pact_dir=PACT_DIR,
        log_dir=PACT_LOG_DIR,
    )

    pact.start_service()
    atexit.register(pact.stop_service)
    return pact
