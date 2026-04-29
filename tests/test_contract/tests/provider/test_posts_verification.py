"""Provider verification: POST /posts accepts the documented request shape
and returns the documented response.

The route's `current_active_user` dependency is overridden by the provider
server fixture (auth-mocked). `handle_create_post` is monkey-patched out via
`MockDataFactory.create_post_create_dependency_config` so this test exercises
only the route layer (the "waiter, not chef" split).
"""

import pytest
from yarl import URL

from tests.test_contract.tests.shared.mock_data_factory import MockDataFactory
from tests.test_contract.tests.shared.provider_verification_base import (
    BaseProviderVerification,
    create_provider_test_decorator,
)


class PostsVerification(BaseProviderVerification):
    """Provider verification for the posts API."""

    @property
    def provider_name(self) -> str:
        return "posts-api"

    @property
    def consumer_name(self) -> str:
        return "post-create-form"

    @property
    def dependency_config(self):
        return MockDataFactory.create_post_create_dependency_config()

    @property
    def pytest_marks(self) -> list:
        return [pytest.mark.provider, pytest.mark.posts]


posts_verification = PostsVerification()


@create_provider_test_decorator(
    posts_verification.dependency_config, "with_posts_api_mocks"
)
def test_provider_posts_pact_verification(provider_server: URL):
    """Verify the post-create-form Pact contract against the running provider server."""
    posts_verification.verify_pact(provider_server)
