import pytest
from yarl import URL

from tests.test_contract.tests.shared.mock_data_factory import MockDataFactory
from tests.test_contract.tests.shared.provider_verification_base import (
    BaseProviderVerification,
    create_provider_test_decorator,
)


class ConversationsVerification(BaseProviderVerification):
    """Conversations provider verification."""

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
            "src.api.routes.conversations.handle_get_conversation": {
                "return_value_config": MockDataFactory.create_conversation(
                    name="mock-name"
                )
            }
        }
        return {**create_config, **get_config}

    @property
    def pytest_marks(self) -> list:
        return [pytest.mark.provider, pytest.mark.conversations]


class MessagesVerification(BaseProviderVerification):
    """Messages provider verification."""

    @property
    def provider_name(self) -> str:
        return "messages-api"

    @property
    def consumer_name(self) -> str:
        return "send-message-form"

    @property
    def dependency_config(self):
        create_message_config = MockDataFactory.create_message_dependency_config()
        get_conversation_config = {
            "src.api.routes.conversations.handle_get_conversation": {
                "return_value_config": MockDataFactory.create_conversation(
                    name="mock-name"
                )
            }
        }
        return {**create_message_config, **get_conversation_config}

    @property
    def pytest_marks(self) -> list:
        return [pytest.mark.provider, pytest.mark.messages]


# Create instances for use in tests
conversations_verification = ConversationsVerification()
messages_verification = MessagesVerification()


@create_provider_test_decorator(
    conversations_verification.dependency_config, "with_conversations_api_mocks"
)
def test_provider_conversations_pact_verification(provider_server: URL):
    """Verify the Conversations Pact contract against the running provider server."""
    conversations_verification.verify_pact(provider_server)


@create_provider_test_decorator(
    messages_verification.dependency_config, "with_messages_api_mocks"
)
def test_provider_messages_pact_verification(provider_server: URL):
    """Verify the Messages Pact contract against the running provider server."""
    messages_verification.verify_pact(provider_server)
