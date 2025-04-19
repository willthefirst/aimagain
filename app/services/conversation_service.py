import uuid
import logging  # Use logging instead of print
from uuid import UUID
from fastapi import (
    HTTPException,
    status,
)  # Keep for potential internal use or re-raising
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from app.models import User, Conversation, Participant, Message
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.user_repository import UserRepository
from app.schemas.participant import ParticipantStatus

# Setup logger
logger = logging.getLogger(__name__)


# Define custom service-level exceptions
class ServiceError(Exception):
    """Base class for service layer errors."""

    def __init__(self, message="An internal service error occurred.", status_code=500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class ConversationNotFoundError(ServiceError):
    def __init__(self, message="Conversation not found."):
        super().__init__(message, status_code=404)


class UserNotFoundError(ServiceError):
    def __init__(self, message="User not found."):
        super().__init__(message, status_code=404)


class NotAuthorizedError(ServiceError):
    def __init__(self, message="User not authorized for this action."):
        super().__init__(message, status_code=403)


class BusinessRuleError(ServiceError):
    """For violations of specific business rules (e.g., user offline)."""

    def __init__(self, message="Action violates business rules."):
        super().__init__(message, status_code=400)  # Often a Bad Request


class ConflictError(ServiceError):
    """For conflicts like trying to add an existing participant."""

    def __init__(self, message="Operation conflicts with existing state."):
        super().__init__(message, status_code=409)


class DatabaseError(ServiceError):
    """For general database errors during service operations."""

    def __init__(self, message="A database error occurred."):
        super().__init__(message, status_code=500)


class ConversationService:
    def __init__(
        self,
        conversation_repository: ConversationRepository,
        participant_repository: ParticipantRepository,
        message_repository: MessageRepository,
        user_repository: UserRepository,
    ):
        self.conv_repo = conversation_repository
        self.part_repo = participant_repository
        self.msg_repo = message_repository
        self.user_repo = user_repository
        # The session is implicitly shared via the repositories
        self.session = (
            conversation_repository.session
        )  # Get session access for commit/rollback

    async def get_conversations_for_listing(self) -> list[Conversation]:
        """Fetches conversations suitable for a public listing."""
        try:
            return await self.conv_repo.list_conversations()
        except SQLAlchemyError as e:
            logger.error(f"Database error listing conversations: {e}", exc_info=True)
            raise DatabaseError("Failed to list conversations due to a database error.")

    async def get_conversation_details(
        self, slug: str, requesting_user: User
    ) -> Conversation:
        """
        Fetches detailed conversation data, including participants and messages,
        performing authorization checks.
        """
        conversation = await self.conv_repo.get_conversation_by_slug(slug)
        if not conversation:
            raise ConversationNotFoundError(
                f"Conversation with slug '{slug}' not found."
            )

        # Authorization Check
        participant = await self.part_repo.get_participant_by_user_and_conversation(
            user_id=requesting_user.id, conversation_id=conversation.id
        )

        if not participant:
            raise NotAuthorizedError("User is not a participant in this conversation.")

        if participant.status != ParticipantStatus.JOINED:
            raise NotAuthorizedError("User has not joined this conversation.")

        # Assuming get_conversation_details loads relations or we load them manually
        # Let's assume the repo method loads them:
        details = await self.conv_repo.get_conversation_details(conversation.id)
        if not details:
            # Should not happen if slug check passed, but handle defensively
            raise ConversationNotFoundError(
                f"Could not fetch details for conversation id '{conversation.id}'."
            )

        # Ensure messages are sorted (repo might do this, but good to confirm)
        details.messages.sort(key=lambda msg: msg.created_at)

        return details

    async def create_new_conversation(
        self,
        creator_user: User,
        invitee_user_id: UUID,
        initial_message_content: str,
    ) -> Conversation:
        """
        Creates a new conversation, an initial message, and participant records
        for the creator (joined) and invitee (invited).
        Handles the transaction.
        """
        invitee_user = await self.user_repo.get_user_by_id(invitee_user_id)
        if not invitee_user:
            raise UserNotFoundError(
                f"Invitee user with ID '{invitee_user_id}' not found."
            )
        if not invitee_user.is_online:
            raise BusinessRuleError("Invitee user is not online.")
        if creator_user.id == invitee_user.id:
            raise BusinessRuleError("Cannot create a conversation with yourself.")

        # Assume conv_repo.create_new_conversation creates all objects and adds to session
        # but does NOT commit.
        try:
            new_conversation = await self.conv_repo.create_new_conversation(
                creator_user=creator_user,
                invitee_user=invitee_user,
                initial_message_content=initial_message_content,
            )

            # Commit the transaction for the entire operation
            await self.session.commit()

            # Refresh to get DB-generated fields (like IDs, timestamps) and relations
            # The repo method might return a refreshed object, or we do it here.
            # Best practice: Refresh the main object and potentially key related ones needed by caller.
            await self.session.refresh(new_conversation)
            # If the response schema needs participant/message details immediately, refresh them too.
            # This depends on what `create_new_conversation` returns and what the API response model needs.
            # Example: assuming relations are loaded by refresh or already populated:
            # await self.session.refresh(new_conversation, attribute_names=['participants', 'messages'])

        except IntegrityError as e:  # Catch potential unique constraint violations etc.
            await self.session.rollback()
            logger.warning(f"Integrity error creating conversation: {e}", exc_info=True)
            raise ConflictError(
                "Could not create conversation due to a data conflict (e.g., duplicate slug)."
            )
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f"Database error creating conversation: {e}", exc_info=True)
            raise DatabaseError(
                "Failed to create conversation due to a database error."
            )
        except Exception as e:  # Catch other potential errors from repo/logic
            await self.session.rollback()
            logger.error(f"Unexpected error creating conversation: {e}", exc_info=True)
            raise ServiceError(
                f"An unexpected error occurred during conversation creation."
            )

        return new_conversation

    async def invite_user_to_conversation(
        self,
        conversation_slug: str,
        invitee_user_id: UUID,
        inviter_user: User,
    ) -> Participant:
        """Invites a user to an existing conversation. Handles the transaction."""
        conversation = await self.conv_repo.get_conversation_by_slug(conversation_slug)
        if not conversation:
            raise ConversationNotFoundError(
                f"Conversation with slug '{conversation_slug}' not found."
            )

        # Authorization check for inviter
        is_joined = await self.part_repo.check_if_user_is_joined_participant(
            user_id=inviter_user.id, conversation_id=conversation.id
        )
        if not is_joined:
            raise NotAuthorizedError(
                "User must be a joined participant to invite others."
            )

        # Invitee validation
        invitee_user = await self.user_repo.get_user_by_id(invitee_user_id)
        if not invitee_user:
            raise UserNotFoundError(
                f"Invitee user with ID '{invitee_user_id}' not found."
            )
        if not invitee_user.is_online:
            raise BusinessRuleError("Invitee user is not online.")
        if inviter_user.id == invitee_user.id:
            raise BusinessRuleError("Cannot invite yourself.")

        existing_participant = (
            await self.part_repo.get_participant_by_user_and_conversation(
                user_id=invitee_user.id, conversation_id=conversation.id
            )
        )
        if existing_participant:
            raise ConflictError("Invitee is already a participant.")

        try:
            # Create participant record using participant repository
            new_participant = await self.part_repo.create_participant(
                user_id=invitee_user.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.INVITED,
                invited_by_user_id=inviter_user.id,
                # No initial message for invites to existing conversations
            )

            # Update conversation timestamps using conversation repository
            await self.conv_repo.update_conversation_timestamps(conversation)

            # Commit changes for participant creation and timestamp update
            await self.session.commit()

            # Refresh the new participant to ensure all fields are loaded post-commit
            await self.session.refresh(new_participant)
            # Optionally refresh conversation if updated timestamps are needed by caller
            # await self.session.refresh(conversation)

        except IntegrityError as e:
            await self.session.rollback()
            logger.warning(f"Integrity error inviting participant: {e}", exc_info=True)
            raise ConflictError("Could not invite participant due to a data conflict.")
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f"Database error inviting participant: {e}", exc_info=True)
            raise DatabaseError("Failed to invite participant due to a database error.")
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Unexpected error inviting participant: {e}", exc_info=True)
            raise ServiceError(f"An unexpected error occurred during invitation.")

        return new_participant
