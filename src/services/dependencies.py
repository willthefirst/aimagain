from fastapi import Depends

from src.repositories.conversation_repository import ConversationRepository
from src.repositories.dependencies import (
    get_conversation_repository,
    get_message_repository,
    get_participant_repository,
    get_user_repository,
)
from src.repositories.message_repository import MessageRepository
from src.repositories.participant_repository import ParticipantRepository
from src.repositories.user_repository import UserRepository

from .conversation_service import ConversationService
from .participant_service import ParticipantService
from .presence_service import PresenceService
from .provider import ServiceProvider
from .user_service import UserService


def get_conversation_service(
    conv_repo: ConversationRepository = Depends(get_conversation_repository),
    part_repo: ParticipantRepository = Depends(get_participant_repository),
    msg_repo: MessageRepository = Depends(get_message_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> ConversationService:
    """Provides an instance of the ConversationService with its dependencies."""
    return ServiceProvider.get_service(
        ConversationService,
        conversation_repository=conv_repo,
        participant_repository=part_repo,
        message_repository=msg_repo,
        user_repository=user_repo,
    )


def get_participant_service(
    part_repo: ParticipantRepository = Depends(get_participant_repository),
    conv_repo: ConversationRepository = Depends(get_conversation_repository),
) -> ParticipantService:
    """Provides an instance of the ParticipantService."""
    return ServiceProvider.get_service(
        ParticipantService,
        participant_repository=part_repo,
        conversation_repository=conv_repo,
    )


def get_user_service(
    part_repo: ParticipantRepository = Depends(get_participant_repository),
    conv_repo: ConversationRepository = Depends(get_conversation_repository),
) -> UserService:
    """Provides an instance of the UserService."""
    return ServiceProvider.get_service(
        UserService,
        participant_repository=part_repo,
        conversation_repository=conv_repo,
    )


def get_presence_service(
    user_repo: UserRepository = Depends(get_user_repository),
) -> PresenceService:
    """Provides an instance of the PresenceService."""
    return ServiceProvider.get_service(
        PresenceService,
        user_repository=user_repo,
    )
