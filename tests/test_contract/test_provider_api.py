from datetime import datetime, timezone
import pytest
import os
from uuid import uuid4
import logging
from typing import Generator, Any
from pact import Verifier
from yarl import URL
from app.models.conversation import Conversation
from tests.test_contract.conftest import PROVIDER_STATE_SETUP_URL
from app.schemas.user import UserRead
from tests.test_contract.test_helpers import PACT_DIR, PACT_LOG_DIR


log = logging.getLogger(__name__)

AUTH_API_PROVIDER_NAME = "auth-api"
CONVERSATIONS_API_PROVIDER_NAME = "conversations-api"


AUTH_API_PACT_FILE_PATH = os.path.join(
    PACT_DIR, f"registration-form-{AUTH_API_PROVIDER_NAME}.json"
)
CONVERSATIONS_API_PACT_FILE_PATH = os.path.join(
    PACT_DIR, f"create-conversation-form-{CONVERSATIONS_API_PROVIDER_NAME}.json"
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

# Mock configurations for parametrization
AUTH_API_MOCKS = REGISTRATION_DEPENDENCY_CONFIG
CONVERSATIONS_API_MOCKS = {
    **CREATE_CONVERSATION_DEPENDENCY_CONFIG,
    **GET_CONVERSATION_DEPENDENCY_CONFIG,
}

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
        provider_states_setup_url=PROVIDER_STATE_SETUP_URL,
    )

    success, logs_dict = verifier.verify_pacts(
        AUTH_API_PACT_FILE_PATH, log_dir=PACT_LOG_DIR
    )

    if success != 0:
        log.error("Auth API Pact verification failed. Logs:")
        try:
            import json

            print(json.dumps(logs_dict, indent=4))
        except ImportError:
            print(logs_dict)
        pytest.fail(
            f"Auth API Pact verification failed (exit code: {success}). Check logs."
        )


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
        provider_states_setup_url=PROVIDER_STATE_SETUP_URL,
    )

    success, logs_dict = verifier.verify_pacts(
        CONVERSATIONS_API_PACT_FILE_PATH, log_dir=PACT_LOG_DIR
    )

    if success != 0:
        log.error("Conversations API Pact verification failed. Logs:")
        try:
            import json

            print(json.dumps(logs_dict, indent=4))
        except ImportError:
            print(logs_dict)
        pytest.fail(
            f"Conversations API Pact verification failed (exit code: {success}). Check logs."
        )
