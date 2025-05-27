"""Provider server management for contract tests."""

import asyncio
import logging
import uuid
from typing import Any, AsyncGenerator, Callable, Dict, Optional

import pytest
import uvicorn
from fastapi import Body, Depends, FastAPI, Response, status
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import get_db_session, get_user_db
from app.main import app
from app.models import User, metadata

from .mock_utilities import (
    MockAuthManager,
    apply_patches_via_monkeypatch,
    create_mock_user,
)
from .server_management import ServerManager, setup_health_check_route

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


class ProviderStateHandler:
    """Handles provider state setup for Pact verification."""

    def __init__(self, known_states: list[str]):
        self.known_states = known_states
        self.logger = logging.getLogger("provider_state_handler")

    def __call__(self, state_info: dict = Body(...)) -> Response:
        """Handle provider state setup requests from Verifier."""
        state = state_info.get("state")
        consumer = state_info.get("consumer", "Unknown Consumer")

        self.logger.info(f"Received provider state '{state}' for consumer '{consumer}'")

        if state in self.known_states:
            self.logger.info(f"Acknowledged known provider state: {state}")
            return Response(status_code=status.HTTP_200_OK)
        else:
            self.logger.warning(f"Unhandled provider state received: {state}")
            return Response(status_code=status.HTTP_200_OK)


def setup_provider_state_route(
    app: FastAPI, state_path: str, state_handler: Callable, logger: logging.Logger
) -> None:
    """Set up the provider state handler route."""
    app.post("/" + state_path)(state_handler)
    logger.info(f"Added state handler at /{state_path} to provider app.")


def setup_provider_database_overrides(app: FastAPI, logger: logging.Logger) -> tuple:
    """Set up database dependency overrides for provider testing."""
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

    app.dependency_overrides[get_db_session] = (
        local_provider_override_get_db_session_impl
    )
    app.dependency_overrides[get_user_db] = local_provider_override_get_user_db_impl

    logger.info("Applied DB dependency overrides for provider test.")

    return provider_test_engine, provider_test_async_session_maker


async def create_database_tables(engine, logger: logging.Logger) -> None:
    """Create database tables for testing."""
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    logger.info("In-memory DB tables created for provider test.")


async def drop_database_tables(engine, logger: logging.Logger) -> None:
    """Drop database tables after testing."""
    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)
    logger.info("In-memory DB tables dropped for provider test.")


def run_provider_server_process(
    host: str,
    port: int,
    state_path: str,
    state_handler: Callable,
    override_config: Optional[Dict[str, Dict]] = None,
) -> None:
    """Target function to run the main FastAPI app with overrides for provider testing."""
    logger = logging.getLogger("provider_server")

    # Store original dependency overrides
    original_dependency_overrides = app.dependency_overrides.copy()

    try:
        # Set up database
        engine, session_maker = setup_provider_database_overrides(app, logger)
        asyncio.run(create_database_tables(engine, logger))

        # Set up routes
        setup_health_check_route(app)
        setup_provider_state_route(app, state_path, state_handler, logger)

        # Set up mock auth
        mock_user = create_mock_user(
            email="provider.mock@example.com",
            username="provider_mock_user",
            user_id=uuid.uuid4(),
        )

        from app.auth_config import current_active_user

        MockAuthManager.setup_mock_auth(app, mock_user, current_active_user)
        logger.info(f"Mocking current_active_user with user: {mock_user.email}")

        # Apply patches
        mp = pytest.MonkeyPatch()
        try:
            apply_patches_via_monkeypatch(mp, override_config, logger)
            uvicorn.run(app, host=host, port=port, log_level="warning")
        finally:
            mp.undo()
            logger.info("MonkeyPatch.undo() called for provider patches.")

        # Clean up database
        asyncio.run(drop_database_tables(engine, logger))

    finally:
        # Restore original dependency overrides
        app.dependency_overrides = original_dependency_overrides
        logger.info("Restored original dependency overrides for provider app.")


class ProviderServerManager(ServerManager):
    """Manages provider test servers."""

    def start_with_state_handler(
        self,
        state_path: str,
        state_handler: Callable,
        override_config: Optional[Dict[str, Dict]] = None,
    ) -> None:
        """Start the provider server with state handler configuration."""
        self.start(
            run_provider_server_process, state_path, state_handler, override_config
        )
