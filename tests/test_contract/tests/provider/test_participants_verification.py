import pytest
from yarl import URL

from tests.test_contract.tests.shared.mock_data_factory import MockDataFactory
from tests.test_contract.tests.shared.provider_verification_base import (
    BaseProviderVerification,
    create_provider_test_decorator,
)


class ParticipantsVerification(BaseProviderVerification):
    """Participants provider verification."""

    @property
    def provider_name(self) -> str:
        return "participants-api"

    @property
    def consumer_name(self) -> str:
        return "invitation-form"

    @property
    def dependency_config(self):
        return MockDataFactory.create_participant_dependency_config()

    @property
    def pytest_marks(self) -> list:
        return [pytest.mark.provider, pytest.mark.participants]


participants_verification = ParticipantsVerification()


@create_provider_test_decorator(
    participants_verification.dependency_config, "with_participants_api_mocks"
)
@pytest.mark.provider
@pytest.mark.participants
def test_provider_participants_pact_verification(provider_server: URL):
    """Verify the Participants Pact contract against the running provider server."""
    participants_verification.verify_pact(provider_server)
