"""Consumer server management for contract tests."""

import logging
import uuid
from typing import Dict, Optional

import uvicorn
from fastapi import FastAPI

from app.api.routes import auth_pages, conversations, me, participants, users
from app.auth_config import current_active_user
from app.models import Conversation, Message, Participant, User
from app.schemas.participant import ParticipantStatus

from ..utilities.mocks import (
    MockAuthManager,
    apply_patches_via_import,
    create_mock_user,
)
from .base import ServerManager, setup_health_check_route


class ConsumerServerConfig:
    """Configuration for consumer server routes and features."""

    def __init__(
        self,
        auth_pages: bool = True,
        conversations: bool = True,
        users_pages: bool = False,
        me_pages: bool = False,
        participants_pages: bool = False,
        mock_invitations: bool = False,
        mock_auth: bool = True,
    ):
        self.auth_pages = auth_pages
        self.conversations = conversations
        self.users_pages = users_pages
        self.me_pages = me_pages
        self.participants_pages = participants_pages
        self.mock_invitations = mock_invitations
        self.mock_auth = mock_auth


def create_mock_invitation_data() -> list:
    """Create mock invitation data for testing."""
    mock_inviter = User(
        id=uuid.uuid4(),
        email="inviter@example.com",
        username="test_inviter",
        is_active=True,
    )

    mock_conversation = Conversation(
        id=uuid.uuid4(),
        slug="test-conversation-slug",
        created_by_user_id=mock_inviter.id,
    )

    mock_initial_message = Message(
        id=uuid.uuid4(),
        content="Hey, want to join our conversation?",
        conversation_id=mock_conversation.id,
        created_by_user_id=mock_inviter.id,
    )

    mock_invitation = Participant(
        id=uuid.UUID("550e8400-e29b-41d4-a716-446655440000"),
        user_id=uuid.uuid4(),
        conversation_id=mock_conversation.id,
        status=ParticipantStatus.INVITED,
        invited_by_user_id=mock_inviter.id,
        initial_message_id=mock_initial_message.id,
    )

    # Set up relationships
    mock_invitation.inviter = mock_inviter
    mock_invitation.conversation = mock_conversation
    mock_invitation.initial_message = mock_initial_message

    return [mock_invitation]


def setup_consumer_app_routes(app: FastAPI, config: ConsumerServerConfig) -> None:
    """Set up routes on the consumer app based on configuration."""
    if config.auth_pages:
        app.include_router(auth_pages.auth_pages_api_router)

    if config.conversations:
        app.include_router(conversations.conversations_router_instance)

    if config.users_pages:
        app.include_router(users.users_api_router)

    if config.me_pages:
        app.include_router(me.me_router_instance)

    if config.participants_pages:
        app.include_router(participants.participants_router_instance)


def setup_consumer_mocks(config: ConsumerServerConfig, logger: logging.Logger) -> None:
    """Set up mocks for the consumer server."""
    if config.mock_invitations:
        logger.info("Adding mock invitations for contract tests")
        mock_invitations = create_mock_invitation_data()

        mock_invitations_config = {
            "app.api.routes.me.handle_get_my_invitations": {
                "return_value_config": mock_invitations
            }
        }
        apply_patches_via_import(mock_invitations_config, logger)


def run_consumer_server_process(
    host: str, port: int, config: Optional[ConsumerServerConfig] = None
) -> None:
    """Target function to run consumer test server uvicorn in a separate process."""
    logger = logging.getLogger("consumer_server")

    if config is None:
        config = ConsumerServerConfig()

    consumer_app = FastAPI(title="Consumer Test Server Process")
    setup_health_check_route(consumer_app)

    # Apply mocks before including routers
    setup_consumer_mocks(config, logger)

    # Set up routes
    setup_consumer_app_routes(consumer_app, config)

    # Set up mock authentication
    if config.mock_auth:
        logger.info("Adding mock auth for contract tests")
        mock_user = create_mock_user(
            email="test@example.com", username="contract_test_user"
        )
        MockAuthManager.setup_mock_auth(consumer_app, mock_user, current_active_user)

    uvicorn.run(consumer_app, host=host, port=port, log_level="warning")


class ConsumerServerManager(ServerManager):
    """Manages consumer test servers."""

    def start_with_config(self, config: Optional[ConsumerServerConfig] = None) -> None:
        """Start the consumer server with the given configuration."""
        self.start(run_consumer_server_process, config)
