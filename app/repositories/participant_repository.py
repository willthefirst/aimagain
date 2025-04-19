import uuid
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy import select, exists
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import Sequence

from .base import BaseRepository
from app.models import (
    Participant,
    User,
    Conversation,
    Message,
)  # Added User, Conversation, Message
from app.schemas.participant import ParticipantStatus  # Assuming you have this enum


class ParticipantRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def create_participant(
        self,
        user_id: UUID,
        conversation_id: UUID,
        status: ParticipantStatus,
        *,
        joined_at: datetime | None = None,
        invited_by_user_id: UUID | None = None,
        initial_message_id: UUID | None = None,
    ) -> Participant:
        """Creates a new participant record."""
        new_participant = Participant(
            user_id=user_id,
            conversation_id=conversation_id,
            status=status,
            invited_by_user_id=invited_by_user_id,
            initial_message_id=initial_message_id,
            joined_at=joined_at,
        )
        self.session.add(new_participant)
        await self.session.flush()
        await self.session.refresh(new_participant)
        return new_participant

    async def get_participant_by_user_and_conversation(
        self, user_id: UUID, conversation_id: UUID
    ) -> Participant | None:
        """Retrieves a participant record by user and conversation ID."""
        stmt = select(Participant).filter(
            Participant.user_id == user_id,
            Participant.conversation_id == conversation_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def check_if_user_is_joined_participant(
        self, user_id: UUID, conversation_id: UUID
    ) -> bool:
        """Checks if a user is a joined participant in a conversation."""
        stmt = select(
            exists().where(
                Participant.user_id == user_id,
                Participant.conversation_id == conversation_id,
                Participant.status == ParticipantStatus.JOINED,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def list_user_invitations(self, user: User) -> Sequence[Participant]:
        """Lists pending invitations for a given user."""
        stmt = (
            select(Participant)
            .where(
                Participant.user_id == user.id,
                Participant.status == ParticipantStatus.INVITED,
            )
            .options(
                # Eager load related data needed for display
                selectinload(Participant.conversation).selectinload(
                    Conversation.creator
                ),
                selectinload(Participant.inviter),
                selectinload(Participant.initial_message),
            )
            .order_by(Participant.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_participant_by_id(self, participant_id: UUID) -> Participant | None:
        """Retrieves a participant record by its ID, optionally loading relations."""
        stmt = select(Participant).filter(Participant.id == participant_id)
        # Optionally add options(...) here if conversation is always needed
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def update_participant_status(
        self,
        participant: Participant,
        new_status: ParticipantStatus,
        expected_current_status: ParticipantStatus | None = None,
    ) -> Participant:
        """Updates the status of a participant, handling timestamp and joined_at.

        Args:
            participant: The Participant ORM instance to update.
            new_status: The target status (enum member).
            expected_current_status: If provided, raises ValueError if the participant's
                                     current status doesn't match.

        Returns:
            The updated Participant instance.

        Raises:
            ValueError: If expected_current_status doesn't match.
        """
        if (
            expected_current_status is not None
            and participant.status != expected_current_status
        ):
            raise ValueError(
                f"Cannot change status from '{participant.status}'. "
                f"Expected '{expected_current_status}'."
            )

        now = datetime.now(timezone.utc)
        participant.status = new_status

        if new_status == ParticipantStatus.JOINED:
            participant.joined_at = now

        self.session.add(participant)
        await self.session.flush()
        await self.session.refresh(participant)
        return participant

    # TODO: Add methods for listing invitations/conversations (me.py) -> list_user_invitations done
    # TODO: Add methods for updating status (participants.py) -> Done
