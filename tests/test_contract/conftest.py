"""Refactored conftest.py for contract tests using modular structure."""

import os
import shutil
from typing import Any, Generator

import pytest
from playwright.async_api import async_playwright
from yarl import URL

from tests.test_contract.tests.consumer.test_conversation_form import (
    PROVIDER_STATE_USER_ONLINE,
)

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

# Add dynamic provider states
KNOWN_PROVIDER_STATES.append(PROVIDER_STATE_USER_ONLINE)


@pytest.fixture(scope="session")
def origin_with_routes(request) -> str:
    """Pytest fixture providing the origin URL for the running consumer test server
    with specified routes.

    Usage:
        @pytest.mark.parametrize("origin_with_routes", [{"auth_pages": True}], indirect=True)
        def test_auth_related(...):
            ...
    """
    # Parse configuration from request parameters
    routes_config_dict = getattr(request, "param", None) or {
        "auth_pages": True,
        "conversations": True,
    }

    # Convert dict to ConsumerServerConfig
    config = ConsumerServerConfig(**routes_config_dict)

    # Start consumer server
    server_manager = ConsumerServerManager(CONSUMER_HOST, CONSUMER_PORT)
    server_manager.start_with_config(config)

    yield str(CONSUMER_BASE_URL)

    server_manager.stop()


@pytest.fixture(scope="session")
async def browser():
    """Pytest fixture to launch a Playwright browser instance."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest.fixture(scope="function")
async def page(browser):
    """Pytest fixture to create a new browser page for each test."""
    page = await browser.new_page()
    yield page
    await page.close()


@pytest.fixture(scope="module")
def provider_server(request) -> Generator[URL, Any, None]:
    """
    Starts the main FastAPI app in a separate process for Pact verification.
    Dependency override/patching configuration is passed via indirect parametrization.
    """
    override_config = getattr(request, "param", None)
    if not (override_config and isinstance(override_config, dict)):
        override_config = None

    # Create state handler
    state_handler = ProviderStateHandler(KNOWN_PROVIDER_STATES)

    # Start provider server
    server_manager = ProviderServerManager(PROVIDER_HOST, PROVIDER_PORT)
    server_manager.start_with_state_handler(
        PROVIDER_STATE_SETUP_ENDPOINT_PATH, state_handler, override_config
    )

    yield PROVIDER_BASE_URL

    server_manager.stop()


@pytest.fixture(scope="session", autouse=True)
def clean_pact_dir_before_session():
    """Ensures the pacts directory is clean before the test session starts."""
    if os.path.exists(PACT_DIR):
        shutil.rmtree(PACT_DIR)
    os.makedirs(PACT_DIR, exist_ok=True)
