import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pact import Verifier
from yarl import URL

from app.models.conversation import Conversation
from app.models.participant import Participant
from app.schemas.participant import ParticipantStatus
from app.schemas.user import UserRead
from tests.test_contract.infrastructure.config import PROVIDER_STATE_SETUP_FULL_URL
from tests.test_contract.tests.shared.helpers import PACT_DIR, PACT_LOG_DIR

log = logging.getLogger(__name__)

AUTH_API_PROVIDER_NAME = "auth-api"
CONVERSATIONS_API_PROVIDER_NAME = "conversations-api"
USERS_API_PROVIDER_NAME = "users-api"
PARTICIPANTS_API_PROVIDER_NAME = "participants-api"

AUTH_API_PACT_FILE_PATH = os.path.join(
    PACT_DIR, f"registration-form-{AUTH_API_PROVIDER_NAME}.json"
)
CONVERSATIONS_API_PACT_FILE_PATH = os.path.join(
    PACT_DIR, f"create-conversation-form-{CONVERSATIONS_API_PROVIDER_NAME}.json"
)
USERS_API_PACT_FILE_PATH = os.path.join(
    PACT_DIR, f"user-list-page-{USERS_API_PROVIDER_NAME}.json"
)
PARTICIPANTS_API_PACT_FILE_PATH = os.path.join(
    PACT_DIR, f"invitation-form-{PARTICIPANTS_API_PROVIDER_NAME}.json"
)

REGISTRATION_DEPENDENCY_CONFIG = {
    "app.api.routes.auth_routes.handle_registration": {
        "return_value_config": UserRead(
            id=str(uuid4()),
            email="test.user@example.com",
            username="testuser",
            is_active=True,
            is_superuser=False,
            is_verified=False,
        )
    }
}

CREATE_CONVERSATION_DEPENDENCY_CONFIG = {
    "app.api.routes.conversations.handle_create_conversation": {
        "return_value_config": Conversation(
            id=str(uuid4()),
            slug="mock-slug",
            created_by_user_id=str(uuid4()),
            last_activity_at=datetime.now(timezone.utc).isoformat(),
        )
    }
}

GET_CONVERSATION_DEPENDENCY_CONFIG = {
    "app.api.routes.conversations.handle_get_conversation": {
        "return_value_config": Conversation(
            id=str(uuid4()),
            name="mock-name",
            slug="mock-slug",
            created_by_user_id=str(uuid4()),
            last_activity_at=datetime.now(timezone.utc).isoformat(),
        )
    }
}

LIST_USERS_DEPENDENCY_CONFIG = {
    "app.logic.user_processing.handle_list_users": {
        "return_value_config": {
            "request": {},
            "users": [
                UserRead(
                    id=str(uuid4()),
                    email="test1@example.com",
                    username="testuser1",
                    is_active=True,
                    is_superuser=False,
                    is_verified=True,
                ),
                UserRead(
                    id=str(uuid4()),
                    email="test2@example.com",
                    username="testuser2",
                    is_active=True,
                    is_superuser=False,
                    is_verified=True,
                ),
            ],
            "current_user": UserRead(
                id=str(uuid4()),
                email="current@example.com",
                username="currentuser",
                is_active=True,
                is_superuser=False,
                is_verified=True,
            ),
        }
    }
}

UPDATE_PARTICIPANT_STATUS_DEPENDENCY_CONFIG = {
    "app.logic.participant_processing.handle_update_participant_status": {
        "return_value_config": Participant(
            id="550e8400-e29b-41d4-a716-446655440000",
            user_id="550e8400-e29b-41d4-a716-446655440001",
            conversation_id="550e8400-e29b-41d4-a716-446655440002",
            status=ParticipantStatus.REJECTED,
            invited_by_user_id="550e8400-e29b-41d4-a716-446655440003",
            initial_message_id="550e8400-e29b-41d4-a716-446655440004",
            created_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            joined_at=None,
        )
    }
}

AUTH_API_MOCKS = REGISTRATION_DEPENDENCY_CONFIG
CONVERSATIONS_API_MOCKS = {
    **CREATE_CONVERSATION_DEPENDENCY_CONFIG,
    **GET_CONVERSATION_DEPENDENCY_CONFIG,
}
USERS_API_MOCKS = LIST_USERS_DEPENDENCY_CONFIG
PARTICIPANTS_API_MOCKS = UPDATE_PARTICIPANT_STATUS_DEPENDENCY_CONFIG

AUTH_API_PROVIDER_DECORATOR = pytest.mark.parametrize(
    "provider_server",
    [AUTH_API_MOCKS],
    indirect=True,
    scope="module",
    ids=["with_auth_api_mocks"],
)

CONVERSATIONS_API_PROVIDER_DECORATOR = pytest.mark.parametrize(
    "provider_server",
    [CONVERSATIONS_API_MOCKS],
    indirect=True,
    scope="module",
    ids=["with_conversations_api_mocks"],
)

USERS_API_PROVIDER_DECORATOR = pytest.mark.parametrize(
    "provider_server",
    [USERS_API_MOCKS],
    indirect=True,
    scope="module",
    ids=["with_users_api_mocks"],
)

PARTICIPANTS_API_PROVIDER_DECORATOR = pytest.mark.parametrize(
    "provider_server",
    [PARTICIPANTS_API_MOCKS],
    indirect=True,
    scope="module",
    ids=["with_participants_api_mocks"],
)


def _verify_pact_and_handle_result(success: int, logs_dict: dict, pact_name: str):
    if success != 0:
        log.error(f"{pact_name} Pact verification failed. Logs:")
        try:
            import json

            print(json.dumps(logs_dict, indent=4))
        except ImportError:
            print(logs_dict)
        except Exception as e:
            log.error(f"Error printing pact logs: {e}")
            print(logs_dict)
        pytest.fail(
            f"{pact_name} Pact verification failed (exit code: {success}). Check logs."
        )


@AUTH_API_PROVIDER_DECORATOR
@pytest.mark.provider
@pytest.mark.auth
def test_provider_auth_api_pact_verification(
    provider_server: URL,
):
    """Verify the Auth API Pact contract against the running provider server."""
    if not os.path.exists(AUTH_API_PACT_FILE_PATH):
        pytest.fail(
            f"Pact file not found: {AUTH_API_PACT_FILE_PATH}. Run consumer test first."
        )

    verifier = Verifier(
        provider=AUTH_API_PROVIDER_NAME,
        provider_base_url=str(provider_server),
        provider_states_setup_url=PROVIDER_STATE_SETUP_FULL_URL,
    )

    success, logs_dict = verifier.verify_pacts(
        AUTH_API_PACT_FILE_PATH, log_dir=PACT_LOG_DIR
    )

    _verify_pact_and_handle_result(success, logs_dict, "Auth API")


@CONVERSATIONS_API_PROVIDER_DECORATOR
@pytest.mark.provider
@pytest.mark.conversations
def test_provider_conversations_api_pact_verification(
    provider_server: URL,
):
    """Verify the Conversations API Pact contract against the running provider server."""
    if not os.path.exists(CONVERSATIONS_API_PACT_FILE_PATH):
        pytest.fail(
            f"Pact file not found: {CONVERSATIONS_API_PACT_FILE_PATH}. Run consumer test first."
        )

    verifier = Verifier(
        provider=CONVERSATIONS_API_PROVIDER_NAME,
        provider_base_url=str(provider_server),
        provider_states_setup_url=PROVIDER_STATE_SETUP_FULL_URL,
    )

    success, logs_dict = verifier.verify_pacts(
        CONVERSATIONS_API_PACT_FILE_PATH, log_dir=PACT_LOG_DIR
    )

    _verify_pact_and_handle_result(success, logs_dict, "Conversations API")


@PARTICIPANTS_API_PROVIDER_DECORATOR
@pytest.mark.provider
@pytest.mark.participants
def test_provider_participants_api_pact_verification(
    provider_server: URL,
):
    """Verify the Participants API Pact contract against the running provider server."""
    if not os.path.exists(PARTICIPANTS_API_PACT_FILE_PATH):
        pytest.fail(
            f"Pact file not found: {PARTICIPANTS_API_PACT_FILE_PATH}. Run consumer test first."
        )

    verifier = Verifier(
        provider=PARTICIPANTS_API_PROVIDER_NAME,
        provider_base_url=str(provider_server),
        provider_states_setup_url=PROVIDER_STATE_SETUP_FULL_URL,
    )

    success, logs_dict = verifier.verify_pacts(
        PARTICIPANTS_API_PACT_FILE_PATH, log_dir=PACT_LOG_DIR
    )

    _verify_pact_and_handle_result(success, logs_dict, "Participants API")
