"""Provider verification: DELETE /posts/{id} accepts the documented request
shape and returns the documented response.

The route's `current_active_user` dependency is overridden by the provider
server fixture (auth-mocked). `handle_delete_post` is monkey-patched out via
the dependency config so this test exercises only the route layer (the
"waiter, not chef" split).

Per-kind create/edit-form contract pairs are deferred until the non-note
kinds' form schemas stabilize.
"""

import pytest
from yarl import URL

from tests.test_contract.tests.shared.mock_data_factory import MockDataFactory
from tests.test_contract.tests.shared.provider_verification_base import (
    BaseProviderVerification,
    create_provider_test_decorator,
)

COMBINED_POSTS_DEPENDENCY_CONFIG = {
    **MockDataFactory.create_post_delete_dependency_config(),
}


class _BasePostsVerification(BaseProviderVerification):
    @property
    def provider_name(self) -> str:
        return "posts-api"

    @property
    def dependency_config(self):
        return COMBINED_POSTS_DEPENDENCY_CONFIG


class PostsOwnerActionsVerification(_BasePostsVerification):
    @property
    def consumer_name(self) -> str:
        return "post-owner-actions"

    @property
    def pytest_marks(self) -> list:
        return [pytest.mark.provider, pytest.mark.posts]


posts_owner_actions_verification = PostsOwnerActionsVerification()


@create_provider_test_decorator(
    COMBINED_POSTS_DEPENDENCY_CONFIG, "with_posts_api_mocks"
)
def test_provider_posts_owner_actions_pact_verification(provider_server: URL):
    """Verify the post-owner-actions Pact contract against the running provider server."""
    posts_owner_actions_verification.verify_pact(provider_server)
