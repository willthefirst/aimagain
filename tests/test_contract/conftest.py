import asyncio
import logging
import multiprocessing
import os
import shutil
import time
import uuid
from typing import Any, AsyncGenerator, Callable, Dict, Generator

import pytest
import requests
import uvicorn
from fastapi import Body, FastAPI, Response, status
from playwright.async_api import async_playwright
from requests.exceptions import ConnectionError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from yarl import URL

from app.api.routes import auth_pages, conversations, me, participants, users
from app.db import get_db_session, get_user_db
from app.models import User, metadata
from tests.test_contract.test_consumer_conversation_form import (
    PROVIDER_STATE_USER_ONLINE,
)

from .test_helpers import PACT_DIR

PACT_LOG_LEVEL = "warning"

PROVIDER_HOST = "127.0.0.1"
PROVIDER_PORT = 8999
PROVIDER_BASE_URL = URL(f"http://{PROVIDER_HOST}:{PROVIDER_PORT}")
PROVIDER_STATE_SETUP_ENDPOINT_PATH = "_pact/provider_states"
PROVIDER_STATE_SETUP_FULL_URL = str(
    PROVIDER_BASE_URL / PROVIDER_STATE_SETUP_ENDPOINT_PATH
)

CONSUMER_HOST = "127.0.0.1"
CONSUMER_PORT = 8990
CONSUMER_BASE_URL = URL(f"http://{CONSUMER_HOST}:{CONSUMER_PORT}")

log_provider = logging.getLogger("pact_provider_test")

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


from fastapi import Depends
from fastapi_users.db import SQLAlchemyUserDatabase

from app.main import app


def provider_states_handler(state_info: dict = Body(...)):
    """Endpoint handler logic for provider state setup requests from Verifier."""
    state = state_info.get("state")
    consumer = state_info.get("consumer", "Unknown Consumer")

    log_provider.info(f"Received provider state '{state}' for consumer '{consumer}'")

    known_states = [
        "User test.user@example.com does not exist",
        PROVIDER_STATE_USER_ONLINE,
    ]

    if state in known_states:
        log_provider.info(f"Acknowledged known provider state: {state}")
        return Response(status_code=status.HTTP_200_OK)
    else:
        log_provider.warning(f"Unhandled provider state received: {state}")
        return Response(status_code=status.HTTP_200_OK)


def _create_mock_user(email: str, username: str, user_id: uuid.UUID = None) -> User:
    """Helper function to create a mock User instance."""
    return User(
        id=user_id if user_id else uuid.uuid4(),
        email=email,
        username=username,
        is_active=True,
    )


def _poll_server_ready(url: str, retries: int = 10, delay: float = 0.5) -> bool:
    """Polls a URL until it's responsive or retries are exhausted."""
    for i in range(retries):
        try:
            response = requests.get(url, timeout=1)
            if response.status_code == 200:
                log_provider.info(f"Server at {url} is ready.")
                return True
        except ConnectionError:
            log_provider.debug(
                f"Server at {url} not ready yet (attempt {i+1}/{retries}). Retrying in {delay}s..."
            )
        except requests.Timeout:
            log_provider.debug(
                f"Server at {url} timed out (attempt {i+1}/{retries}). Retrying in {delay}s..."
            )
        time.sleep(delay)
    log_provider.error(f"Server at {url} failed to start after {retries} retries.")
    return False


def run_consumer_server_process(
    host: str, port: int, routes_config=None, mock_auth=True
):
    """Target function to run consumer test server uvicorn in a separate process.

    Args:
        host: Host address to bind to
        port: Port to bind to
        routes_config: Dict with keys as router modules and values as booleans to include/exclude
    """
    from app.auth_config import current_active_user

    consumer_app = FastAPI(title="Consumer Test Server Process")

    @consumer_app.get("/_health")
    async def health_check():
        return {"status": "ok"}

    if routes_config is None:
        routes_config = {
            "auth_pages": True,
            "conversations": True,
            "users_pages": False,
            "me_pages": False,
            "participants_pages": False,
        }

    if routes_config.get("auth_pages", False):
        consumer_app.include_router(auth_pages.auth_pages_api_router)

    if routes_config.get("conversations", False):
        consumer_app.include_router(conversations.conversations_router_instance)

    if routes_config.get("users_pages", False):
        consumer_app.include_router(users.users_api_router)

    if routes_config.get("me_pages", False):
        consumer_app.include_router(me.me_router_instance)

    if routes_config.get("participants_pages", False):
        consumer_app.include_router(participants.participants_router_instance)

    if mock_auth:
        print
        log_provider.info("Adding mock auth for contract tests")
        mock_user = _create_mock_user(
            email="test@example.com", username="contract_test_user"
        )

        async def get_mock_current_user():
            return mock_user

        consumer_app.dependency_overrides[current_active_user] = get_mock_current_user

    uvicorn.run(consumer_app, host=host, port=port, log_level="warning")


def _start_consumer_server_process(
    host: str, port: int, routes_config=None, mock_auth=True
) -> multiprocessing.Process:
    """Starts the consumer test FastAPI server in a separate process."""
    server_process = multiprocessing.Process(
        target=run_consumer_server_process,
        args=(host, port, routes_config, mock_auth),
        daemon=True,
    )
    server_process.start()
    health_check_url = f"http://{host}:{port}/_health"
    if not _poll_server_ready(health_check_url):
        _terminate_server_process(server_process)
        raise RuntimeError(
            f"Consumer server process failed to start at {health_check_url}"
        )
    return server_process


def _terminate_server_process(
    process: multiprocessing.Process,
):
    """Terminates the server process."""
    process.terminate()
    process.join(timeout=3)
    if process.is_alive():
        logger = logging.getLogger("test_server_termination")
        logger.warning(
            f"Server process {process.pid} did not terminate gracefully. Killing."
        )
        process.kill()
        process.join(timeout=1)


@pytest.fixture(scope="session")
def origin_with_routes(request) -> str:
    """Pytest fixture providing the origin URL for the running consumer test server
    with specified routes.

    Usage:
        @pytest.mark.parametrize("origin_with_routes", [{"auth_pages": True}], indirect=True)
        def test_auth_related(...):
            ...
    """
    routes_config = getattr(request, "param", None) or {
        "auth_pages": True,
        "conversations": True,
    }

    mock_auth = True
    if isinstance(routes_config, dict) and "mock_auth" in routes_config:
        mock_auth = routes_config.pop("mock_auth")

    origin_url = str(CONSUMER_BASE_URL)
    server_process = _start_consumer_server_process(
        CONSUMER_HOST, CONSUMER_PORT, routes_config, mock_auth
    )
    yield origin_url
    _terminate_server_process(server_process)


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


def _setup_provider_app_routes(
    app: FastAPI, state_path: str, state_handler: Callable, log: logging.Logger
):
    """Sets up health check and state handler routes for the provider app."""

    @app.get("/_health")
    async def health_check():
        return {"status": "ok"}

    log.info("Added /_health endpoint to provider app.")

    app.post("/" + state_path)(state_handler)
    log.info(f"Added state handler at /{state_path} to provider app.")


def _setup_provider_mock_auth(app: FastAPI, log: logging.Logger):
    """Sets up mock authentication for the provider app."""
    import uuid

    from app.auth_config import current_active_user
    from app.models import User

    mock_user_instance = _create_mock_user(
        email="provider.mock@example.com",
        username="provider_mock_user",
        user_id=uuid.uuid4(),
    )

    async def get_mock_provider_user():
        return mock_user_instance

    app.dependency_overrides[current_active_user] = get_mock_provider_user
    log.info(f"Mocking current_active_user with user: {mock_user_instance.email}")
    return current_active_user


def _apply_provider_patches(
    mp: pytest.MonkeyPatch, override_config: Dict[str, Dict], log: logging.Logger
):
    """Applies patches based on override_config using MonkeyPatch."""
    import uuid
    from unittest.mock import AsyncMock

    if not override_config:
        return

    for patch_target_path, mock_config in override_config.items():
        try:
            if "return_value_config" in mock_config:
                return_data = mock_config["return_value_config"]
                if (
                    isinstance(return_data, dict)
                    and "id" in return_data
                    and isinstance(return_data["id"], str)
                ):
                    try:
                        uuid_obj = uuid.UUID(return_data["id"])
                        return_data["id"] = uuid_obj
                    except ValueError:
                        log.debug(
                            f"Could not convert id '{return_data['id']}' to UUID for {patch_target_path}. Using string."
                        )
                        pass
                mock_instance = AsyncMock(return_value=return_data)
            else:
                mock_instance = AsyncMock()

            mp.setattr(patch_target_path, mock_instance)
            log.info(
                f"Applied patch for '{patch_target_path}' with mock: {mock_instance}"
            )
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            log.error(f"Failed to setup mock/patch for '{patch_target_path}': {e}")
            raise RuntimeError(
                f"Failed to setup mock/patch for '{patch_target_path}'"
            ) from e


def _run_provider_server_process(
    host: str,
    port: int,
    state_path: str,
    state_handler: Callable,
    override_config: Dict[str, Dict] | None,
) -> None:
    """Target function to run the main FastAPI app with overrides for provider testing."""
    provider_test_engine = create_async_engine(TEST_DATABASE_URL)
    provider_test_async_session_maker = async_sessionmaker(
        provider_test_engine, expire_on_commit=False
    )

    async def local_provider_override_get_db_session_impl() -> (
        AsyncGenerator[AsyncSession, None]
    ):
        async with provider_test_async_session_maker() as session:
            yield session

    async def local_provider_override_get_user_db_impl(
        session: AsyncSession = Depends(local_provider_override_get_db_session_impl),
    ) -> SQLAlchemyUserDatabase[User, Any]:
        yield SQLAlchemyUserDatabase(session, User)

    log_provider_subprocess = logging.getLogger("pact_provider_test_subprocess")

    original_dependency_overrides = app.dependency_overrides.copy()

    try:

        async def create_db_tables():
            async with provider_test_engine.begin() as conn:
                await conn.run_sync(metadata.create_all)
            log_provider_subprocess.info(
                "In-memory DB tables created for provider test."
            )

        asyncio.run(create_db_tables())

        app.dependency_overrides[get_db_session] = (
            local_provider_override_get_db_session_impl
        )
        app.dependency_overrides[get_user_db] = local_provider_override_get_user_db_impl
        log_provider_subprocess.info(
            "Applied DB dependency overrides for provider test."
        )

        _setup_provider_app_routes(
            app, state_path, state_handler, log_provider_subprocess
        )

        _setup_provider_mock_auth(app, log_provider_subprocess)

        mp = pytest.MonkeyPatch()
        try:
            _apply_provider_patches(mp, override_config, log_provider_subprocess)

            uvicorn.run(app, host=host, port=port, log_level=PACT_LOG_LEVEL)

        finally:
            mp.undo()
            log_provider_subprocess.info(
                "MonkeyPatch.undo() called for provider patches."
            )

    finally:

        async def drop_db_tables():
            async with provider_test_engine.begin() as conn:
                await conn.run_sync(metadata.drop_all)
            log_provider_subprocess.info(
                "In-memory DB tables dropped for provider test."
            )

        asyncio.run(drop_db_tables())

        app.dependency_overrides = original_dependency_overrides
        log_provider_subprocess.info(
            "Restored original dependency overrides for provider app."
        )


@pytest.fixture(scope="module")
def provider_server(request) -> Generator[URL, Any, None]:
    """
    Starts the main FastAPI app in a separate process for Pact verification.
    Dependency override/patching configuration is passed via indirect parametrization.
    """
    override_config = getattr(request, "param", None)
    if not (override_config and isinstance(override_config, dict)):
        override_config = None

    process_args = (
        PROVIDER_HOST,
        PROVIDER_PORT,
        PROVIDER_STATE_SETUP_ENDPOINT_PATH,
        provider_states_handler,
        override_config,
    )

    proc = multiprocessing.Process(
        target=_run_provider_server_process,
        args=process_args,
        daemon=True,
    )
    proc.start()

    health_check_url = f"{PROVIDER_BASE_URL}/_health"
    if not _poll_server_ready(health_check_url, retries=20, delay=0.5):
        _terminate_server_process(proc)
        pytest.fail("Provider server process failed to start.", pytrace=False)

    yield PROVIDER_BASE_URL

    _terminate_server_process(proc)


@pytest.fixture(scope="session", autouse=True)
def clean_pact_dir_before_session():
    """Ensures the pacts directory is clean before the test session starts."""
    if os.path.exists(PACT_DIR):
        shutil.rmtree(PACT_DIR)
    os.makedirs(PACT_DIR, exist_ok=True)
