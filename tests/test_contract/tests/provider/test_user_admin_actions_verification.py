"""Provider verification: PUT /users/{id}/activation accepts the documented
shape and returns the documented response.

The route's `current_admin_user` dependency is overridden by the consumer
server fixture (auth-mocked). `handle_set_user_activation` is monkey-patched
out via `MockDataFactory.create_user_activation_dependency_config` so this
test exercises only the route layer.
"""

import pytest
from yarl import URL

from tests.test_contract.tests.shared.mock_data_factory import MockDataFactory
from tests.test_contract.tests.shared.provider_verification_base import (
    BaseProviderVerification,
    create_provider_test_decorator,
)


class UserAdminActionsVerification(BaseProviderVerification):
    """Provider verification for the user admin-actions API."""

    @property
    def provider_name(self) -> str:
        return "users-api"

    @property
    def consumer_name(self) -> str:
        return "user-admin-actions"

    @property
    def dependency_config(self):
        return MockDataFactory.create_user_activation_dependency_config()

    @property
    def pytest_marks(self) -> list:
        return [pytest.mark.provider, pytest.mark.users]


user_admin_actions_verification = UserAdminActionsVerification()


@create_provider_test_decorator(
    user_admin_actions_verification.dependency_config, "with_users_api_mocks"
)
def test_provider_user_admin_actions_pact_verification(provider_server: URL):
    """Verify the user-admin-actions Pact contract against the running provider server."""
    user_admin_actions_verification.verify_pact(provider_server)
