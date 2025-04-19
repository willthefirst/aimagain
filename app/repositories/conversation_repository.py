from typing import Sequence
from sqlalchemy import select
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
from datetime import datetime, timezone

from .base import BaseRepository
from app.models import Conversation, Participant, User, Message


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

    async def get_conversation_by_id(self, conversation_id: str) -> Conversation | None:
        """Retrieves a specific conversation by its ID."""
        stmt = select(Conversation).filter(Conversation.id == conversation_id)
        # Add options here if needed (e.g., participants) depending on usage
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_conversation_details(
        self, conversation_id: str
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
        # Assuming ID is unique and should return one result
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

        # 1. Create Conversation
        new_conversation = Conversation(
            id=f"conv_{uuid.uuid4()}",
            slug=slug,
            created_by_user_id=creator_user.id,
            last_activity_at=now,  # Set initial activity time
            # created_at/updated_at handled by defaults
        )
        self.session.add(new_conversation)
        await self.session.flush()  # Need ID for message/participants

        # 2. Create initial Message
        initial_message = Message(
            id=f"msg_{uuid.uuid4()}",
            content=initial_message_content,
            conversation_id=new_conversation.id,
            created_by_user_id=creator_user.id,
            created_at=now,  # Match conversation activity time
        )
        self.session.add(initial_message)
        await self.session.flush()  # Need ID for invitee participant

        # 3. Create Participant for creator
        creator_participant = Participant(
            id=f"part_{uuid.uuid4()}",
            user_id=creator_user.id,
            conversation_id=new_conversation.id,
            status="joined",
            joined_at=now,
        )
        self.session.add(creator_participant)

        # 4. Create Participant for invitee
        invitee_participant = Participant(
            id=f"part_{uuid.uuid4()}",
            user_id=invitee_user.id,
            conversation_id=new_conversation.id,
            status="invited",
            invited_by_user_id=creator_user.id,
            initial_message_id=initial_message.id,
        )
        self.session.add(invitee_participant)

        # Flush to ensure all objects are persisted before potential refresh
        await self.session.flush()
        # Refresh the conversation to load relationships if needed by caller
        await self.session.refresh(new_conversation)

        return new_conversation

    async def update_conversation_timestamps(self, conversation: Conversation) -> None:
        """Updates the updated_at and last_activity_at timestamps for a conversation."""
        now = datetime.now(timezone.utc)
        conversation.updated_at = now
        conversation.last_activity_at = now
        self.session.add(conversation)  # Add to session to mark for update
        await self.session.flush()
        await self.session.refresh(conversation)

    async def list_user_conversations(self, user: User) -> Sequence[Conversation]:
        """Lists conversations a given user has joined."""
        stmt = (
            select(Conversation)
            .join(Participant, Conversation.id == Participant.conversation_id)
            .filter(
                Participant.user_id == user.id,
                Participant.status == "joined",
            )
            .options(
                # Eager load participants and their users
                selectinload(Conversation.participants).joinedload(Participant.user),
            )
            .order_by(Conversation.last_activity_at.desc().nullslast())
            .distinct()  # Ensure unique conversations if multiple joins occur (though unlikely here)
        )
        result = await self.session.execute(stmt)
        # .unique() might be needed if relationships cause duplicates, but distinct() in SQL is better
        return result.scalars().all()

    async def update_conversation_activity(
        self, conversation: Conversation, activity_time: datetime | None = None
    ) -> None:
        """Updates the last_activity_at and updated_at timestamps of a conversation."""
        now = activity_time or datetime.now(timezone.utc)
        conversation.last_activity_at = now
        conversation.updated_at = now
        self.session.add(conversation)
        await self.session.flush()
        await self.session.refresh(conversation)

    # TODO: Add methods for create_conversation and invite_participant logic
