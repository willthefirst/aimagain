from datetime import datetime, timezone
import pytest
import os
from uuid import uuid4
import logging
from typing import Generator, Any
from pact import Verifier
from yarl import URL
from app.models.conversation import Conversation
from tests.test_contract.conftest import PROVIDER_STATE_SETUP_FULL_URL
from app.schemas.user import UserRead
from tests.test_contract.test_helpers import PACT_DIR, PACT_LOG_DIR


log = logging.getLogger(__name__)

AUTH_API_PROVIDER_NAME = "auth-api"
CONVERSATIONS_API_PROVIDER_NAME = "conversations-api"
USERS_API_PROVIDER_NAME = "users-api"


AUTH_API_PACT_FILE_PATH = os.path.join(
    PACT_DIR, f"registration-form-{AUTH_API_PROVIDER_NAME}.json"
)
CONVERSATIONS_API_PACT_FILE_PATH = os.path.join(
    PACT_DIR, f"create-conversation-form-{CONVERSATIONS_API_PROVIDER_NAME}.json"
)
USERS_API_PACT_FILE_PATH = os.path.join(
    PACT_DIR, f"user-list-page-{USERS_API_PROVIDER_NAME}.json"
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

# Mock configurations for parametrization
AUTH_API_MOCKS = REGISTRATION_DEPENDENCY_CONFIG
CONVERSATIONS_API_MOCKS = {
    **CREATE_CONVERSATION_DEPENDENCY_CONFIG,
    **GET_CONVERSATION_DEPENDENCY_CONFIG,
}
USERS_API_MOCKS = LIST_USERS_DEPENDENCY_CONFIG

# Pytest parametrize decorators for provider_server fixture
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


def _verify_pact_and_handle_result(success: int, logs_dict: dict, pact_name: str):
    if success != 0:
        log.error(f"{pact_name} Pact verification failed. Logs:")
        try:
            import json

            print(json.dumps(logs_dict, indent=4))
        except ImportError:  # Should not happen if json is a standard library
            print(logs_dict)
        except Exception as e:
            log.error(f"Error printing pact logs: {e}")
            print(logs_dict)  # Fallback to raw print
        pytest.fail(
            f"{pact_name} Pact verification failed (exit code: {success}). Check logs."
        )


@AUTH_API_PROVIDER_DECORATOR
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


@USERS_API_PROVIDER_DECORATOR
def test_provider_users_api_pact_verification(
    provider_server: URL,
):
    """Verify the Users API Pact contract against the running provider server."""
    if not os.path.exists(USERS_API_PACT_FILE_PATH):
        pytest.fail(
            f"Pact file not found: {USERS_API_PACT_FILE_PATH}. Run consumer test first."
        )

    verifier = Verifier(
        provider=USERS_API_PROVIDER_NAME,
        provider_base_url=str(provider_server),
        provider_states_setup_url=PROVIDER_STATE_SETUP_FULL_URL,
    )

    success, logs_dict = verifier.verify_pacts(
        USERS_API_PACT_FILE_PATH, log_dir=PACT_LOG_DIR
    )

    _verify_pact_and_handle_result(success, logs_dict, "Users API")
