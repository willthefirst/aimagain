"""Provider verification: POST /posts, PATCH /posts/{id}, and DELETE
/posts/{id} accept the documented request shapes and return the documented
responses.

The route's `current_active_user` dependency is overridden by the provider
server fixture (auth-mocked). `handle_create_post`, `handle_update_post`,
and `handle_delete_post` are monkey-patched out via the combined dependency
config so this test exercises only the route layer (the "waiter, not chef"
split).

Only `client_referral` is exercised on PATCH — `provider_availability` has
no editable fields yet, so there is no Update variant for that kind.

One module-scoped provider server with all three mocks applied — every pact
file verifies against the same server.
"""

import pytest
from yarl import URL

from tests.test_contract.tests.shared.mock_data_factory import MockDataFactory
from tests.test_contract.tests.shared.provider_verification_base import (
    BaseProviderVerification,
    create_provider_test_decorator,
)

COMBINED_POSTS_DEPENDENCY_CONFIG = {
    **MockDataFactory.create_post_create_dependency_config(),
    **MockDataFactory.create_post_edit_dependency_config(),
    **MockDataFactory.create_post_delete_dependency_config(),
}


class _BasePostsVerification(BaseProviderVerification):
    @property
    def provider_name(self) -> str:
        return "posts-api"

    @property
    def dependency_config(self):
        return COMBINED_POSTS_DEPENDENCY_CONFIG


class PostsCreateVerification(_BasePostsVerification):
    @property
    def consumer_name(self) -> str:
        return "post-create-form"

    @property
    def pytest_marks(self) -> list:
        return [pytest.mark.provider, pytest.mark.posts]


class PostsEditVerification(_BasePostsVerification):
    @property
    def consumer_name(self) -> str:
        return "post-edit-form"

    @property
    def pytest_marks(self) -> list:
        return [pytest.mark.provider, pytest.mark.posts]


class PostsOwnerActionsVerification(_BasePostsVerification):
    @property
    def consumer_name(self) -> str:
        return "post-owner-actions"

    @property
    def pytest_marks(self) -> list:
        return [pytest.mark.provider, pytest.mark.posts]


posts_create_verification = PostsCreateVerification()
posts_edit_verification = PostsEditVerification()
posts_owner_actions_verification = PostsOwnerActionsVerification()


@create_provider_test_decorator(
    COMBINED_POSTS_DEPENDENCY_CONFIG, "with_posts_api_mocks"
)
def test_provider_posts_create_pact_verification(provider_server: URL):
    """Verify the post-create-form Pact contract against the running provider server."""
    posts_create_verification.verify_pact(provider_server)


@create_provider_test_decorator(
    COMBINED_POSTS_DEPENDENCY_CONFIG, "with_posts_api_mocks"
)
def test_provider_posts_edit_pact_verification(provider_server: URL):
    """Verify the post-edit-form Pact contract against the running provider server."""
    posts_edit_verification.verify_pact(provider_server)


@create_provider_test_decorator(
    COMBINED_POSTS_DEPENDENCY_CONFIG, "with_posts_api_mocks"
)
def test_provider_posts_owner_actions_pact_verification(provider_server: URL):
    """Verify the post-owner-actions Pact contract against the running provider server."""
    posts_owner_actions_verification.verify_pact(provider_server)
