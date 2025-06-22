import logging

from src.models import User
from src.services.user_service import UserService

logger = logging.getLogger(__name__)


async def handle_get_my_invitations(
    user: User,
    user_service: UserService,
):
    """Handles the core logic for retrieving the current user's invitations."""
    invitations = await user_service.get_user_invitations(user=user)
    return invitations


async def handle_get_my_conversations(
    user: User,
    user_service: UserService,
):
    """Handles the core logic for retrieving the current user's conversations."""
    conversations = await user_service.get_user_conversations(user=user)
    return conversations
