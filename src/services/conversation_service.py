import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.models import Conversation, Participant, User
from src.repositories.conversation_repository import ConversationRepository
from src.repositories.message_repository import MessageRepository
from src.repositories.participant_repository import ParticipantRepository
from src.repositories.user_repository import UserRepository
from src.schemas.participant import ParticipantStatus

from .exceptions import (
    BusinessRuleError,
    ConflictError,
    ConversationNotFoundError,
    DatabaseError,
    NotAuthorizedError,
    ServiceError,
    UserNotFoundError,
)

logger = logging.getLogger(__name__)


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
        self.session = conversation_repository.session

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

        participant = await self.part_repo.get_participant_by_user_and_conversation(
            user_id=requesting_user.id, conversation_id=conversation.id
        )

        if not participant:
            raise NotAuthorizedError("User is not a participant in this conversation.")

        if participant.status != ParticipantStatus.JOINED:
            raise NotAuthorizedError("User has not joined this conversation.")

        details = await self.conv_repo.get_conversation_details(conversation.id)
        if not details:
            raise ConversationNotFoundError(
                f"Could not fetch details for conversation id '{conversation.id}'."
            )

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

        try:
            new_conversation = await self.conv_repo.create_new_conversation(
                creator_user=creator_user,
                invitee_user=invitee_user,
                initial_message_content=initial_message_content,
            )

            await self.session.commit()

            await self.session.refresh(new_conversation)

        except IntegrityError as e:
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
        except Exception as e:
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

        is_joined = await self.part_repo.check_if_user_is_joined_participant(
            user_id=inviter_user.id, conversation_id=conversation.id
        )
        if not is_joined:
            raise NotAuthorizedError(
                "User must be a joined participant to invite others."
            )

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
            new_participant = await self.part_repo.create_participant(
                user_id=invitee_user.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.INVITED,
                invited_by_user_id=inviter_user.id,
            )

            await self.conv_repo.update_conversation_timestamps(conversation)

            await self.session.commit()

            await self.session.refresh(new_participant)

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

    async def create_message_in_conversation(
        self,
        conversation_slug: str,
        message_content: str,
        sender_user: User,
    ) -> None:
        """Creates a new message in a conversation and updates the conversation timestamp."""
        conversation = await self.conv_repo.get_conversation_by_slug(conversation_slug)
        if not conversation:
            raise ConversationNotFoundError(
                f"Conversation with slug '{conversation_slug}' not found."
            )

        # Check if user is a joined participant
        is_joined = await self.part_repo.check_if_user_is_joined_participant(
            user_id=sender_user.id, conversation_id=conversation.id
        )
        if not is_joined:
            raise NotAuthorizedError(
                "User must be a joined participant to send messages."
            )

        try:
            # Create the message
            await self.msg_repo.create_message(
                content=message_content,
                conversation_id=conversation.id,
                user_id=sender_user.id,
            )

            # Update conversation timestamp
            await self.conv_repo.update_conversation_timestamps(conversation)

            await self.session.commit()

        except IntegrityError as e:
            await self.session.rollback()
            logger.warning(f"Integrity error creating message: {e}", exc_info=True)
            raise ConflictError("Could not create message due to a data conflict.")
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f"Database error creating message: {e}", exc_info=True)
            raise DatabaseError("Failed to create message due to a database error.")
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Unexpected error creating message: {e}", exc_info=True)
            raise ServiceError(f"An unexpected error occurred during message creation.")
