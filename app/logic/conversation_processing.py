import logging  # Use logging
from uuid import UUID  # Add UUID import

from fastapi import Request

# Logic related to processing conversation actions, decoupled from API routes.
# This helps in testing the core business logic independently.
from app.models import User
from app.models.conversation import Conversation
from app.repositories.user_repository import UserRepository
from app.services.conversation_service import ServiceError  # Base exception
from app.services.conversation_service import (
    BusinessRuleError,
    ConflictError,
    ConversationNotFoundError,
    ConversationService,
    DatabaseError,
    NotAuthorizedError,
)
from app.services.conversation_service import UserNotFoundError
from app.services.conversation_service import (
    UserNotFoundError as ServiceUserNotFoundError,  # Alias to avoid clash
)

logger = logging.getLogger(__name__)  # Setup logger for route level

# Potentially import RepositoryUserNotFoundError if different from service one
# from app.repositories.exceptions import UserNotFoundError as RepoUserNotFoundError


class UserNotFoundError(Exception):
    """Custom exception for user not found in this logic layer."""


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
    # request: Request, # Removed as it's not used directly in the core logic
    requesting_user: User,  # Pass user explicitly
    conv_service: ConversationService,  # Pass service explicitly
):
    """Retrieves details for a specific conversation if the user is authorized."""
    logger.debug(
        f"Handler: Getting conversation details for slug: {slug} by user {requesting_user.id}"
    )
    try:
        # Service method handles fetching and authorization
        # Service exceptions (ConversationNotFoundError, NotAuthorizedError, ServiceError) will propagate.
        conversation_details = await conv_service.get_conversation_details(
            slug=slug, requesting_user=requesting_user
        )

        logger.info(
            f"Handler: Conversation details retrieved: {conversation_details.id if conversation_details else 'None'}"
        )
        return conversation_details
    # Handle specific service errors by re-raising them for the route to handle.
    except (ConversationNotFoundError, NotAuthorizedError, ServiceError) as e:
        logger.info(f"Handler: Service error getting conversation {slug}: {e}")
        raise  # Re-raise for the route to handle
    except Exception as e:
        logger.error(
            f"Handler: Unexpected error getting conversation {slug}: {e}", exc_info=True
        )
        # Wrap unexpected errors in a generic ServiceError for the route to handle consistently
        raise ServiceError(
            f"An unexpected error occurred while retrieving conversation {slug}."
        )


async def handle_list_conversations(
    conv_service: ConversationService,
):
    """Handles the core logic for listing all public conversations."""
    try:
        # Delegate to the service
        conversations = await conv_service.get_conversations_for_listing()
        return conversations
    except DatabaseError as e:
        # Propagate specific errors to be handled by the route
        logger.error(f"Database error listing conversations: {e}", exc_info=True)
        raise  # Re-raise for the route to handle
    except ServiceError as e:
        # Propagate generic service errors
        logger.error(f"Service error listing conversations: {e}", exc_info=True)
        raise  # Re-raise for the route to handle
    except Exception as e:
        # Catch unexpected errors within the handler
        logger.error(
            f"Unexpected error in handle_list_conversations: {e}", exc_info=True
        )
        # Wrap in a generic ServiceError or a new specific logic error
        raise ServiceError("An unexpected error occurred while listing conversations.")


async def handle_get_new_conversation_form(
    request: Request,
    # user: User, # Add if template context needs authenticated user details
):
    """
    Handles the logic for displaying the new conversation form.
    Currently, this is simple and primarily for pattern consistency.
    """
    # The primary responsibility is to gather any data needed by the template.
    # For a simple form display, this might just be the request object.
    # If the form needed, e.g., a list of suggested users, that logic would go here.
    # For now, it doesn't do much beyond what the route could do directly,
    # but it establishes the pattern.
    return {"request": request}  # Context for the template


async def handle_invite_participant(
    conversation_slug: str,
    invitee_user_id_str: str,
    inviter_user: User,
    conv_service: ConversationService,
):
    """Handles the core logic for inviting a user to a conversation."""
    try:
        # Validate UUID format
        try:
            invitee_uuid = UUID(invitee_user_id_str)
        except ValueError:
            # Raise a specific, catchable error for invalid ID format
            # This could be a custom LogicError or re-use BusinessRuleError if appropriate
            raise BusinessRuleError("Invalid invitee user ID format.")

        # Delegate invitation to the service
        new_participant = await conv_service.invite_user_to_conversation(
            conversation_slug=conversation_slug,
            invitee_user_id=invitee_uuid,
            inviter_user=inviter_user,
        )
        return new_participant
    except (
        ConversationNotFoundError,
        NotAuthorizedError,
        ServiceUserNotFoundError,  # Use the aliased UserNotFoundError from service
        BusinessRuleError,
        ConflictError,
        DatabaseError,
    ) as e:
        # Propagate known service errors for the route to handle
        logger.info(
            f"Service error during invitation: {e}"
        )  # Info level for expected errors
        raise
    except ServiceError as e:
        # Propagate generic service errors
        logger.error(f"Generic service error during invitation: {e}", exc_info=True)
        raise
    except Exception as e:
        # Catch unexpected errors
        logger.error(
            f"Unexpected error in handle_invite_participant: {e}", exc_info=True
        )
        raise ServiceError(
            "An unexpected error occurred during the invitation process."
        )
