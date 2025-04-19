from fastapi import Depends

# Import repository dependencies
from app.repositories.dependencies import (
    get_conversation_repository,
    get_participant_repository,
    get_message_repository,
    get_user_repository,
)

# Import repository types (needed for service constructor type hints)
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.user_repository import UserRepository

# Import the service class
from .conversation_service import ConversationService

# Import other services here as they are created
from .participant_service import ParticipantService
from .user_service import UserService


# Dependency function to provide ConversationService instance
def get_conversation_service(
    # Depend on the repository providers
    conv_repo: ConversationRepository = Depends(get_conversation_repository),
    part_repo: ParticipantRepository = Depends(get_participant_repository),
    msg_repo: MessageRepository = Depends(get_message_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    # Note: All repositories implicitly depend on get_db_session,
    # ensuring they share the same AsyncSession instance per request.
) -> ConversationService:
    """Provides an instance of the ConversationService with its dependencies."""
    return ConversationService(
        conversation_repository=conv_repo,
        participant_repository=part_repo,
        message_repository=msg_repo,
        user_repository=user_repo,
    )


# Add dependency functions for other services here...


def get_participant_service(
    part_repo: ParticipantRepository = Depends(get_participant_repository),
    conv_repo: ConversationRepository = Depends(get_conversation_repository),
) -> ParticipantService:
    """Provides an instance of the ParticipantService."""
    return ParticipantService(
        participant_repository=part_repo,
        conversation_repository=conv_repo,
    )


# Add dependency provider for UserService
def get_user_service(
    part_repo: ParticipantRepository = Depends(get_participant_repository),
    conv_repo: ConversationRepository = Depends(get_conversation_repository),
) -> UserService:
    """Provides an instance of the UserService."""
    return UserService(
        participant_repository=part_repo,
        conversation_repository=conv_repo,
    )
