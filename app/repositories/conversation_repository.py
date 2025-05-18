import uuid
from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Conversation, Message, Participant, User
from app.schemas.participant import ParticipantStatus

from .base import BaseRepository


class ConversationRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def list_conversations(self) -> Sequence[Conversation]:
        """Lists all public conversations using ORM, ordered by last activity."""
        stmt = (
            select(Conversation)
            .options(
                selectinload(Conversation.participants).joinedload(Participant.user)
            )
            .order_by(Conversation.last_activity_at.desc().nullslast())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_conversation_by_slug(self, slug: str) -> Conversation | None:
        """Retrieves a specific conversation by its slug."""
        stmt = select(Conversation).filter(Conversation.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_conversation_by_id(
        self, conversation_id: UUID
    ) -> Conversation | None:
        """Retrieves a specific conversation by its ID."""
        stmt = select(Conversation).filter(Conversation.id == conversation_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_conversation_details(
        self, conversation_id: UUID
    ) -> Conversation | None:
        """Retrieves full conversation details including participants and messages."""
        stmt = (
            select(Conversation)
            .filter(Conversation.id == conversation_id)
            .options(
                selectinload(Conversation.participants).joinedload(Participant.user),
                selectinload(Conversation.messages).joinedload(Message.sender),
            )
        )
        result = await self.session.execute(stmt)
        try:
            return result.scalars().one()
        except Exception:  # Handle case where conversation might not be found
            return None

    async def create_new_conversation(
        self, creator_user: User, invitee_user: User, initial_message_content: str
    ) -> Conversation:
        """Creates a new conversation, initial message, and participants."""
        now = datetime.now(timezone.utc)
        slug = f"convo-{uuid.uuid4()}"

        new_conversation = Conversation(
            slug=slug,
            created_by_user_id=creator_user.id,
            last_activity_at=now,
        )
        self.session.add(new_conversation)
        await self.session.flush()

        initial_message = Message(
            content=initial_message_content,
            conversation_id=new_conversation.id,
            created_by_user_id=creator_user.id,
            created_at=now,
        )
        self.session.add(initial_message)
        await self.session.flush()

        creator_participant = Participant(
            user_id=creator_user.id,
            conversation_id=new_conversation.id,
            status=ParticipantStatus.JOINED,
            joined_at=now,
        )
        self.session.add(creator_participant)

        invitee_participant = Participant(
            user_id=invitee_user.id,
            conversation_id=new_conversation.id,
            status=ParticipantStatus.INVITED,
            invited_by_user_id=creator_user.id,
            initial_message_id=initial_message.id,
        )
        self.session.add(invitee_participant)

        await self.session.flush()
        await self.session.refresh(new_conversation)

        return new_conversation

    async def update_conversation_timestamps(self, conversation: Conversation) -> None:
        """Updates the updated_at and last_activity_at timestamps for a conversation."""
        now = datetime.now(timezone.utc)
        conversation.last_activity_at = now
        self.session.add(conversation)
        await self.session.flush()
        await self.session.refresh(conversation)

    async def list_user_conversations(self, user: User) -> Sequence[Conversation]:
        """Lists conversations a given user has joined."""
        stmt = (
            select(Conversation)
            .join(Participant, Conversation.id == Participant.conversation_id)
            .filter(
                Participant.user_id == user.id,
                Participant.status == ParticipantStatus.JOINED,
            )
            .options(
                selectinload(Conversation.participants).joinedload(Participant.user),
            )
            .order_by(Conversation.last_activity_at.desc().nullslast())
            .distinct()
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_conversation_activity(
        self, conversation: Conversation, activity_time: datetime | None = None
    ) -> None:
        """Updates the last_activity_at and updated_at timestamps of a conversation."""
        now = activity_time or datetime.now(timezone.utc)
        conversation.last_activity_at = now
        self.session.add(conversation)
        await self.session.flush()
        await self.session.refresh(conversation)

    # TODO: Add methods for create_conversation and invite_participant logic
