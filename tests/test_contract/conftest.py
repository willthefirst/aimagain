"""Pytest fixtures for contract tests.

Spins up two long-lived processes for the test session:

- A *consumer* server that hosts the HTML pages whose `<form>` submissions are
  the contract under test. Its outbound API calls are intercepted by Playwright
  and routed to the Pact mock service.
- A *provider* server that runs the real `src.main:app`, with business-logic
  handlers monkey-patched out so verification covers route shape only (the
  "waiter, not chef" split documented in the README).
"""

import os
import shutil
from typing import Any, Generator

import pytest
from playwright.async_api import async_playwright
from yarl import URL

from .infrastructure.config import (
    CONSUMER_BASE_URL,
    CONSUMER_HOST,
    CONSUMER_PORT,
    KNOWN_PROVIDER_STATES,
    PACT_DIR,
    PROVIDER_BASE_URL,
    PROVIDER_HOST,
    PROVIDER_PORT,
    PROVIDER_STATE_SETUP_ENDPOINT_PATH,
)
from .infrastructure.servers.consumer import ConsumerServerConfig, ConsumerServerManager
from .infrastructure.servers.provider import ProviderServerManager, ProviderStateHandler


@pytest.fixture(scope="session")
def origin_with_routes(request) -> str:
    """Origin URL of a consumer test server configured per the test's parameters.

    Usage:
        @pytest.mark.parametrize("origin_with_routes", [{"auth_pages": True}], indirect=True)
        def test_register_form(...):
            ...
    """
    routes_config_dict = getattr(request, "param", None) or {"auth_pages": True}

    config = ConsumerServerConfig(**routes_config_dict)

    server_manager = ConsumerServerManager(CONSUMER_HOST, CONSUMER_PORT)
    server_manager.start_with_config(config)

    yield str(CONSUMER_BASE_URL)

    server_manager.stop()


@pytest.fixture(scope="session")
async def browser():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest.fixture(scope="function")
async def page(browser):
    page = await browser.new_page()
    yield page
    await page.close()


@pytest.fixture(scope="module")
def provider_server(request) -> Generator[URL, Any, None]:
    """Run `src.main:app` in a subprocess with handler-level mocks for Pact verification.

    The `request.param` (passed via indirect parametrize) is a mapping of
    fully-qualified handler paths to mock-config dicts; see
    `tests/shared/mock_data_factory.py` for the shape.
    """
    override_config = getattr(request, "param", None)
    if not (override_config and isinstance(override_config, dict)):
        override_config = None

    state_handler = ProviderStateHandler(KNOWN_PROVIDER_STATES)

    server_manager = ProviderServerManager(PROVIDER_HOST, PROVIDER_PORT)
    server_manager.start_with_state_handler(
        PROVIDER_STATE_SETUP_ENDPOINT_PATH, state_handler, override_config
    )

    yield PROVIDER_BASE_URL

    server_manager.stop()


@pytest.fixture(scope="session", autouse=True)
def clean_pact_dir_before_session():
    if os.path.exists(PACT_DIR):
        shutil.rmtree(PACT_DIR)
    os.makedirs(PACT_DIR, exist_ok=True)
