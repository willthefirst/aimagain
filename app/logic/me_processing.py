import logging
from app.models import User
from app.services.user_service import UserService
from app.services.exceptions import (
    DatabaseError,
    ServiceError,
)  # Ensure these are imported if raised

logger = logging.getLogger(__name__)


async def handle_get_my_invitations(
    user: User,
    user_service: UserService,
):
    """Handles the core logic for retrieving the current user's invitations."""
    # Service exceptions (DatabaseError, ServiceError) will propagate up
    # if they occur, to be handled by the route.
    invitations = await user_service.get_user_invitations(user=user)
    return invitations


async def handle_get_my_conversations(
    user: User,
    user_service: UserService,
):
    """Handles the core logic for retrieving the current user's conversations."""
    # Service exceptions (DatabaseError, ServiceError) will propagate up
    # if they occur, to be handled by the route.
    conversations = await user_service.get_user_conversations(user=user)
    return conversations
