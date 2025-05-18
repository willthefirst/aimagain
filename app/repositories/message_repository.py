import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message
from app.repositories.base import BaseRepository


class MessageRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def create_message(
        self, content: str, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> Message:
        """Creates and adds a new message to the session."""
        new_message = Message(
            id=uuid.uuid4(),
            content=content,
            conversation_id=conversation_id,
            created_by_user_id=user_id,
        )
        self.session.add(new_message)
        await self.session.flush()
        return new_message

    async def get_messages_by_conversation(
        self, conversation_id: uuid.UUID
    ) -> list[Message]:
        """Retrieves all messages for a given conversation, ordered by creation time."""
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
