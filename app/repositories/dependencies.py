from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from .conversation_repository import ConversationRepository
from .user_repository import UserRepository
from .participant_repository import ParticipantRepository

# Import other repositories here as they are created
from .message_repository import MessageRepository


def get_conversation_repository(
    session: AsyncSession = Depends(get_db_session),
) -> ConversationRepository:
    return ConversationRepository(session)


# Define dependency providers for other repositories here
def get_user_repository(
    session: AsyncSession = Depends(get_db_session),
) -> UserRepository:
    """Dependency provider for UserRepository."""
    return UserRepository(session)


def get_participant_repository(
    session: AsyncSession = Depends(get_db_session),
) -> ParticipantRepository:
    """Dependency provider for ParticipantRepository."""
    return ParticipantRepository(session)


# Add dependency provider for MessageRepository
def get_message_repository(
    session: AsyncSession = Depends(get_db_session),
) -> MessageRepository:
    """Dependency provider for MessageRepository."""
    return MessageRepository(session)


# def get_message_repository(...):
#     ...
