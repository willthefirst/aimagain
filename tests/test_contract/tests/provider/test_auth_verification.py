import pytest
from yarl import URL

from tests.test_contract.tests.shared.mock_data_factory import MockDataFactory
from tests.test_contract.tests.shared.provider_verification_base import (
    BaseProviderVerification,
    create_provider_test_decorator,
)


class AuthVerification(BaseProviderVerification):
    """Auth provider verification."""

    @property
    def provider_name(self) -> str:
        return "auth-api"

    @property
    def consumer_name(self) -> str:
        return "registration-form"

    @property
    def dependency_config(self):
        return MockDataFactory.create_registration_dependency_config()

    @property
    def pytest_marks(self) -> list:
        return [pytest.mark.provider, pytest.mark.auth]


auth_verification = AuthVerification()


@create_provider_test_decorator(
    auth_verification.dependency_config, "with_auth_api_mocks"
)
@pytest.mark.provider
@pytest.mark.auth
def test_provider_auth_pact_verification(provider_server: URL):
    """Verify the Auth Pact contract against the running provider server."""
    auth_verification.verify_pact(provider_server)
