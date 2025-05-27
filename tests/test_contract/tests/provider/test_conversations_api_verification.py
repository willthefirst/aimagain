import pytest
from yarl import URL

from tests.test_contract.tests.shared.mock_data_factory import MockDataFactory
from tests.test_contract.tests.shared.provider_verification_base import (
    BaseProviderVerification,
    create_provider_test_decorator,
)


class ConversationsApiVerification(BaseProviderVerification):
    """Conversations API provider verification."""

    @property
    def provider_name(self) -> str:
        return "conversations-api"

    @property
    def consumer_name(self) -> str:
        return "create-conversation-form"

    @property
    def dependency_config(self):
        # Combine both create and get conversation configs
        create_config = MockDataFactory.create_conversation_dependency_config()
        get_config = {
            "app.api.routes.conversations.handle_get_conversation": {
                "return_value_config": MockDataFactory.create_conversation(
                    name="mock-name"
                )
            }
        }
        return {**create_config, **get_config}

    @property
    def pytest_marks(self) -> list:
        return [pytest.mark.provider, pytest.mark.conversations]


conversations_verification = ConversationsApiVerification()


@create_provider_test_decorator(
    conversations_verification.dependency_config, "with_conversations_api_mocks"
)
@pytest.mark.provider
@pytest.mark.conversations
def test_provider_conversations_api_pact_verification(provider_server: URL):
    """Verify the Conversations API Pact contract against the running provider server."""
    conversations_verification.verify_pact(provider_server)
