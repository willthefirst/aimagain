from fastapi import APIRouter, Request, Depends, HTTPException, status, Form

import logging  # Use logging


# Logic related to processing conversation actions, decoupled from API routes.
# This helps in testing the core business logic independently.
from app.auth_config import current_active_user
from app.core.templating import templates

from fastapi import Depends, Request
from app.models import User
from app.models.conversation import Conversation
from app.services.conversation_service import (
    ConversationService,
    BusinessRuleError,
    ConflictError,
    DatabaseError,
    ServiceError,
    UserNotFoundError as ServiceUserNotFoundError,  # Alias to avoid clash
)
from app.services.conversation_service import (
    ConversationService,
    ServiceError,  # Base exception
    ConversationNotFoundError,
    NotAuthorizedError,
    UserNotFoundError,
    BusinessRuleError,
    ConflictError,
    DatabaseError,
)
from app.api.errors import handle_service_error

from app.repositories.user_repository import UserRepository
from app.services.dependencies import get_conversation_service


logger = logging.getLogger(__name__)  # Setup logger for route level

# Potentially import RepositoryUserNotFoundError if different from service one
# from app.repositories.exceptions import UserNotFoundError as RepoUserNotFoundError


class UserNotFoundError(Exception):
    """Custom exception for user not found in this logic layer."""

    pass


async def handle_create_conversation(
    invitee_username: str,
    initial_message: str,
    creator_user: User,
    conv_service: ConversationService,
    user_repo: UserRepository,
) -> Conversation:
    """
    Handles the core logic for creating a new conversation based on form input.

    Args:
        invitee_username: The username of the user to invite.
        initial_message: The initial message content.
        creator_user: The user initiating the conversation.
        conv_service: The conversation service dependency.
        user_repo: The user repository dependency.

    Returns:
        The slug of the newly created conversation.

    Raises:
        UserNotFoundError: If the invitee user cannot be found by username.
        BusinessRuleError: If a business rule is violated (e.g., invitee offline).
        ConflictError: If there's a conflict (e.g., conversation already exists).
        DatabaseError: If a database error occurs during creation.
        ServiceError: For other generic service-level errors.
    """
    # 1. Find invitee user by username
    invitee_user = await user_repo.get_user_by_username(invitee_username)
    if not invitee_user:
        # Raise specific exception for this layer
        raise UserNotFoundError(f"User with username '{invitee_username}' not found.")

    # Optional: Check if invitee is online (if business rule still applies)
    # if not invitee_user.is_online:
    #     # Raise service exception directly
    #     raise BusinessRuleError("Invitee user is not online")

    # 2. Delegate creation to the service
    # Service exceptions (BusinessRuleError, ConflictError, DatabaseError, ServiceError)
    # will propagate up if they occur.
    new_conversation = await conv_service.create_new_conversation(
        creator_user=creator_user,
        invitee_user_id=invitee_user.id,
        initial_message_content=initial_message,
    )

    # 3. Return the slug on success
    return new_conversation


async def handle_get_conversation(
    slug: str,
    request: Request,
    user: User = Depends(current_active_user),  # Requires auth
    # Depend on the service
    conv_service: ConversationService = Depends(get_conversation_service),
):
    """Retrieves details for a specific conversation if the user is authorized."""
    print(f"Getting conversation details for slug: {slug}")
    try:
        # Service method handles fetching and authorization
        conversation_details = await conv_service.get_conversation_details(
            slug=slug, requesting_user=user
        )

        logger.info(f"Conversation details in handle_get: {conversation_details}")

        # Service already sorted messages if implemented that way
        # sorted_messages = sorted(
        #     conversation_details.messages, key=lambda msg: msg.created_at
        # )

        return conversation_details
    # Handle specific service errors
    except (ConversationNotFoundError, NotAuthorizedError) as e:
        handle_service_error(e)
    except ServiceError as e:
        # Catch-all for other potential service errors
        handle_service_error(e)
    except Exception as e:
        logger.error(
            f"Unexpected error getting conversation {slug}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=500, detail="An unexpected server error occurred."
        )
