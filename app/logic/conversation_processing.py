import logging
from uuid import UUID

from fastapi import Request

from app.models import User
from app.models.conversation import Conversation
from app.repositories.user_repository import UserRepository
from app.services.conversation_service import (
    BusinessRuleError,
    ConflictError,
    ConversationNotFoundError,
    ConversationService,
    DatabaseError,
    NotAuthorizedError,
    ServiceError,
)
from app.services.conversation_service import UserNotFoundError
from app.services.conversation_service import (
    UserNotFoundError as ServiceUserNotFoundError,
)

logger = logging.getLogger(__name__)


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

    invitee_user = await user_repo.get_user_by_username(invitee_username)
    if not invitee_user:

        raise UserNotFoundError(f"User with username '{invitee_username}' not found.")

    new_conversation = await conv_service.create_new_conversation(
        creator_user=creator_user,
        invitee_user_id=invitee_user.id,
        initial_message_content=initial_message,
    )

    return new_conversation


async def handle_get_conversation(
    slug: str,
    requesting_user: User,
    conv_service: ConversationService,
):
    """Retrieves details for a specific conversation if the user is authorized."""
    logger.debug(
        f"Handler: Getting conversation details for slug: {slug} by user {requesting_user.id}"
    )
    try:

        conversation_details = await conv_service.get_conversation_details(
            slug=slug, requesting_user=requesting_user
        )

        logger.info(
            f"Handler: Conversation details retrieved: {conversation_details.id if conversation_details else 'None'}"
        )
        return conversation_details

    except (ConversationNotFoundError, NotAuthorizedError, ServiceError) as e:
        logger.info(f"Handler: Service error getting conversation {slug}: {e}")
        raise
    except Exception as e:
        logger.error(
            f"Handler: Unexpected error getting conversation {slug}: {e}", exc_info=True
        )

        raise ServiceError(
            f"An unexpected error occurred while retrieving conversation {slug}."
        )


async def handle_list_conversations(
    conv_service: ConversationService,
):
    """Handles the core logic for listing all public conversations."""
    try:

        conversations = await conv_service.get_conversations_for_listing()
        return conversations
    except DatabaseError as e:

        logger.error(f"Database error listing conversations: {e}", exc_info=True)
        raise
    except ServiceError as e:

        logger.error(f"Service error listing conversations: {e}", exc_info=True)
        raise
    except Exception as e:

        logger.error(
            f"Unexpected error in handle_list_conversations: {e}", exc_info=True
        )

        raise ServiceError("An unexpected error occurred while listing conversations.")


async def handle_get_new_conversation_form(
    request: Request,
):
    """
    Handles the logic for displaying the new conversation form.
    Currently, this is simple and primarily for pattern consistency.
    """

    return {"request": request}


async def handle_invite_participant(
    conversation_slug: str,
    invitee_user_id_str: str,
    inviter_user: User,
    conv_service: ConversationService,
):
    """Handles the core logic for inviting a user to a conversation."""
    try:
        try:
            invitee_uuid = UUID(invitee_user_id_str)
        except ValueError:
            raise BusinessRuleError("Invalid invitee user ID format.")

        new_participant = await conv_service.invite_user_to_conversation(
            conversation_slug=conversation_slug,
            invitee_user_id=invitee_uuid,
            inviter_user=inviter_user,
        )
        return new_participant
    except (
        ConversationNotFoundError,
        NotAuthorizedError,
        ServiceUserNotFoundError,
        BusinessRuleError,
        ConflictError,
        DatabaseError,
    ) as e:

        logger.info(f"Service error during invitation: {e}")
        raise
    except ServiceError as e:

        logger.error(f"Generic service error during invitation: {e}", exc_info=True)
        raise
    except Exception as e:

        logger.error(
            f"Unexpected error in handle_invite_participant: {e}", exc_info=True
        )
        raise ServiceError(
            "An unexpected error occurred during the invitation process."
        )
