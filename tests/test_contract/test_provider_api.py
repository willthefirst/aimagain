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
from tests.test_contract.test_consumer_auth_form import CONSUMER_NAME, PROVIDER_NAME
from tests.test_contract.test_helpers import PACT_DIR, PACT_LOG_DIR


log = logging.getLogger(__name__)
Pact_file_path = os.path.join(PACT_DIR, f"{CONSUMER_NAME}-{PROVIDER_NAME}.json")

AUTH_API_PROVIDER_CONFIG = pytest.mark.parametrize(
    "provider_server",
    [
        {
            # Mocks the handler for when a new users registers
            "app.api.routes.auth_routes.handle_registration": {  # Dependency path string
                "return_value_config": UserRead(
                    id=str(uuid4()),
                    email="test.user@example.com",
                    username="testuser",
                    is_active=True,
                    is_superuser=False,
                    is_verified=False,
                )
            },
            # TODO break this out so that it only mocks for the relebant test
            # Mocks the handler for when user creates a conversation
            "app.api.routes.conversations.handle_create_conversation": {  # Dependency path string
                "return_value_config": Conversation(
                    id=str(uuid4()),
                    slug="mock-slug",
                    created_by_user_id=str(uuid4()),
                    last_activity_at=datetime.now(timezone.utc).isoformat(),
                )
            },
            # Mocks the handler for when user gets a conversation
            "app.api.routes.conversations.handle_get_conversation": {  # Dependency path string
                "return_value_config": Conversation(
                    id=str(uuid4()),
                    name="mock-name",
                    slug="mock-slug",
                    created_by_user_id=str(uuid4()),
                    last_activity_at=datetime.now(timezone.utc).isoformat(),
                )
            },
        }
    ],
    indirect=True,
    scope="module",
    ids=["with_mock_registration"],
)


@AUTH_API_PROVIDER_CONFIG
def test_provider_auth_api_pact_verification(
    provider_server: URL,
):
    """Verify the Auth Routes Pact contract against the running provider server."""
    if not os.path.exists(Pact_file_path):
        pytest.fail(f"Pact file not found: {Pact_file_path}. Run consumer test first.")

    verifier = Verifier(
        provider=PROVIDER_NAME,
        provider_base_url=str(provider_server),
        provider_states_setup_url=PROVIDER_STATE_SETUP_URL,
    )

    success, logs_dict = verifier.verify_pacts(Pact_file_path, log_dir=PACT_LOG_DIR)

    if success != 0:
        log.error("Pact verification failed. Logs:")
        try:
            import json

            print(json.dumps(logs_dict, indent=4))
        except ImportError:
            print(logs_dict)
        pytest.fail(f"Pact verification failed (exit code: {success}). Check logs.")
