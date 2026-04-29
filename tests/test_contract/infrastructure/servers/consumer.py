"""Consumer server management for contract tests.

The consumer server hosts only the HTML page(s) whose form submission is the
contract under test. It is deliberately minimal — Playwright drives a browser
against it, intercepts the outbound API call, and forwards it to the Pact mock
service. Anything that talks to a real database or service is out of scope.
"""

import logging
from typing import Optional

import uvicorn
from fastapi import FastAPI

from src.api.routes import auth_pages
from src.auth_config import current_active_user

from ..utilities.mocks import MockAuthManager, create_mock_user
from .base import ServerManager, setup_health_check_route


class ConsumerServerConfig:
    """Toggles for which page routes the consumer server should mount.

    Add a new flag (and a matching `app.include_router(...)` call in
    `setup_consumer_app_routes`) when introducing a contract test pair for a
    new HTML form.
    """

    def __init__(
        self,
        auth_pages: bool = True,
        mock_auth: bool = True,
    ):
        self.auth_pages = auth_pages
        self.mock_auth = mock_auth


def setup_consumer_app_routes(app: FastAPI, config: ConsumerServerConfig) -> None:
    if config.auth_pages:
        app.include_router(auth_pages.auth_pages_api_router)


def run_consumer_server_process(
    host: str, port: int, config: Optional[ConsumerServerConfig] = None
) -> None:
    logger = logging.getLogger("consumer_server")

    if config is None:
        config = ConsumerServerConfig()

    consumer_app = FastAPI(title="Consumer Test Server Process")
    setup_health_check_route(consumer_app)

    setup_consumer_app_routes(consumer_app, config)

    if config.mock_auth:
        logger.info("Adding mock auth for contract tests")
        mock_user = create_mock_user(
            email="test@example.com", username="contract_test_user"
        )
        MockAuthManager.setup_mock_auth(consumer_app, mock_user, current_active_user)

    uvicorn.run(consumer_app, host=host, port=port, log_level="warning")


class ConsumerServerManager(ServerManager):
    def start_with_config(self, config: Optional[ConsumerServerConfig] = None) -> None:
        self.start(run_consumer_server_process, config)
