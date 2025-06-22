"""Factory for creating consistent mock data across contract tests."""

from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

from src.models.conversation import Conversation
from src.models.message import Message
from src.models.participant import Participant
from src.schemas.participant import ParticipantStatus
from src.schemas.user import UserRead


class MockDataFactory:
    """Factory for creating consistent mock data."""

    # Standard test IDs for consistency
    MOCK_USER_ID = "550e8400-e29b-41d4-a716-446655440001"
    MOCK_CONVERSATION_ID = "550e8400-e29b-41d4-a716-446655440002"
    MOCK_PARTICIPANT_ID = "550e8400-e29b-41d4-a716-446655440000"
    MOCK_INVITER_ID = "550e8400-e29b-41d4-a716-446655440003"
    MOCK_MESSAGE_ID = "550e8400-e29b-41d4-a716-446655440004"

    # Standard test data
    TEST_EMAIL = "test.user@example.com"
    TEST_USERNAME = "testuser"
    TEST_PASSWORD = "securepassword123"
    TEST_CONVERSATION_SLUG = "mock-slug"
    TEST_CONVERSATION_NAME = "mock-name"

    @classmethod
    def create_user_read(
        self,
        user_id: str = None,
        email: str = None,
        username: str = None,
        is_active: bool = True,
        is_superuser: bool = False,
        is_verified: bool = False,
    ) -> UserRead:
        """Create a UserRead instance with default or provided values."""
        return UserRead(
            id=user_id or str(uuid4()),
            email=email or self.TEST_EMAIL,
            username=username or self.TEST_USERNAME,
            is_active=is_active,
            is_superuser=is_superuser,
            is_verified=is_verified,
        )

    @classmethod
    def create_conversation(
        self,
        conversation_id: str = None,
        name: str = None,
        slug: str = None,
        created_by_user_id: str = None,
        last_activity_at: str = None,
    ) -> Conversation:
        """Create a Conversation instance with default or provided values."""
        return Conversation(
            id=conversation_id or str(uuid4()),
            name=name or self.TEST_CONVERSATION_NAME,
            slug=slug or self.TEST_CONVERSATION_SLUG,
            created_by_user_id=created_by_user_id or str(uuid4()),
            last_activity_at=last_activity_at or datetime.now(timezone.utc).isoformat(),
        )

    @classmethod
    def create_participant(
        self,
        participant_id: str = None,
        user_id: str = None,
        conversation_id: str = None,
        status: ParticipantStatus = ParticipantStatus.REJECTED,
        invited_by_user_id: str = None,
        initial_message_id: str = None,
        created_at: datetime = None,
        updated_at: datetime = None,
        joined_at: datetime = None,
    ) -> Participant:
        """Create a Participant instance with default or provided values."""
        default_datetime = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        return Participant(
            id=participant_id or self.MOCK_PARTICIPANT_ID,
            user_id=user_id or self.MOCK_USER_ID,
            conversation_id=conversation_id or self.MOCK_CONVERSATION_ID,
            status=status,
            invited_by_user_id=invited_by_user_id or self.MOCK_INVITER_ID,
            initial_message_id=initial_message_id or self.MOCK_MESSAGE_ID,
            created_at=created_at or default_datetime,
            updated_at=updated_at or default_datetime,
            joined_at=joined_at,
        )

    @classmethod
    def create_participant_response_body(
        self,
        participant_id: str = None,
        user_id: str = None,
        conversation_id: str = None,
        status: str = "rejected",
        invited_by_user_id: str = None,
        initial_message_id: str = None,
        created_at: str = "2024-01-01T00:00:00Z",
        updated_at: str = "2024-01-01T00:00:00Z",
        joined_at: str = None,
    ) -> Dict[str, Any]:
        """Create a participant response body for API responses."""
        return {
            "id": participant_id or self.MOCK_PARTICIPANT_ID,
            "user_id": user_id or self.MOCK_USER_ID,
            "conversation_id": conversation_id or self.MOCK_CONVERSATION_ID,
            "status": status,
            "invited_by_user_id": invited_by_user_id or self.MOCK_INVITER_ID,
            "initial_message_id": initial_message_id or self.MOCK_MESSAGE_ID,
            "created_at": created_at,
            "updated_at": updated_at,
            "joined_at": joined_at,
        }

    @classmethod
    def create_registration_dependency_config(
        self, user_read: UserRead = None
    ) -> Dict[str, Any]:
        """Create dependency config for registration endpoint."""
        if user_read is None:
            user_read = self.create_user_read()

        return {
            "src.api.routes.auth_routes.handle_registration": {
                "return_value_config": user_read
            }
        }

    @classmethod
    def create_conversation_dependency_config(
        self, conversation: Conversation = None
    ) -> Dict[str, Any]:
        """Create dependency config for conversation endpoints."""
        if conversation is None:
            conversation = self.create_conversation()

        return {
            "src.api.routes.conversations.handle_create_conversation": {
                "return_value_config": conversation
            }
        }

    @classmethod
    def create_participant_dependency_config(
        self, participant: Participant = None
    ) -> Dict[str, Any]:
        """Create dependency config for participant endpoints."""
        if participant is None:
            participant = self.create_participant()

        return {
            "src.api.routes.participants.handle_update_participant_status": {
                "return_value_config": participant
            }
        }

    @classmethod
    def create_message(cls, **overrides) -> Message:
        """Create a Message instance with default or provided values."""
        return Message(
            id=overrides.get("id", cls.MOCK_MESSAGE_ID),
            content=overrides.get("content", "Test message"),
            conversation_id=overrides.get("conversation_id", cls.MOCK_CONVERSATION_ID),
            created_by_user_id=overrides.get("created_by_user_id", cls.MOCK_USER_ID),
            created_at=overrides.get("created_at", datetime.now(timezone.utc)),
        )

    @classmethod
    def create_message_dependency_config(cls) -> Dict[str, Any]:
        """Create mock config for message endpoints."""
        return {
            "src.api.routes.conversations.handle_create_message": {
                "return_value_config": None  # handle_create_message returns None
            }
        }
