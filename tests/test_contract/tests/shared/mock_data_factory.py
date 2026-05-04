"""Factory for consistent mock data and dependency-override configs.

Each `create_*_dependency_config()` returns a mapping of fully-qualified
handler paths to mock configuration. The provider server fixture
(`tests/test_contract/conftest.py::provider_server`) consumes this mapping to
monkey-patch business-logic handlers, so Pact verification exercises only the
route layer.
"""

from datetime import datetime, timezone
from typing import Any, Dict
from uuid import UUID, uuid4

from src.schemas.post import PostRead
from src.schemas.user import UserRead


class MockDataFactory:
    """Factory for creating consistent mock data."""

    MOCK_USER_ID = "550e8400-e29b-41d4-a716-446655440001"

    TEST_EMAIL = "test.user@example.com"
    TEST_USERNAME = "testuser"
    TEST_PASSWORD = "securepassword123"

    @classmethod
    def create_user_read(
        cls,
        user_id: str = None,
        email: str = None,
        username: str = None,
        is_active: bool = True,
        is_superuser: bool = False,
        is_verified: bool = False,
    ) -> UserRead:
        return UserRead(
            id=user_id or str(uuid4()),
            email=email or cls.TEST_EMAIL,
            username=username or cls.TEST_USERNAME,
            is_active=is_active,
            is_superuser=is_superuser,
            is_verified=is_verified,
        )

    @classmethod
    def create_registration_dependency_config(
        cls, user_read: UserRead = None
    ) -> Dict[str, Any]:
        if user_read is None:
            user_read = cls.create_user_read()

        return {
            "src.api.routes.auth_routes.handle_registration": {
                "return_value_config": user_read
            }
        }

    @classmethod
    def create_user_activation_dependency_config(
        cls, user_read: UserRead = None
    ) -> Dict[str, Any]:
        """Mock for `handle_set_user_activation`.

        The route under test (`PUT /users/{id}/activation`) reads `id`,
        `username`, and `is_active` off the handler's return value and packs
        them into the JSON response, so a `UserRead` (or any object exposing
        those attributes) is sufficient.
        """
        if user_read is None:
            user_read = cls.create_user_read(is_active=False)

        return {
            "src.api.routes.users.handle_set_user_activation": {
                "return_value_config": user_read
            }
        }

    # Stable post id matching `STUB_POST_ID` in `tests/test_contract/constants.py`.
    MOCK_POST_ID = UUID("22222222-2222-2222-2222-222222222222")
    MOCK_POST_OWNER_ID = UUID(MOCK_USER_ID)

    @classmethod
    def create_post_read(
        cls,
        post_id: UUID = None,
        title: str = "stub title",
        body: str = "stub body",
        owner_id: UUID = None,
    ) -> PostRead:
        now = datetime.now(timezone.utc)
        return PostRead(
            id=post_id or cls.MOCK_POST_ID,
            title=title,
            body=body,
            owner_id=owner_id or cls.MOCK_POST_OWNER_ID,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def create_post_create_dependency_config(
        cls, post_read: PostRead = None
    ) -> Dict[str, Any]:
        """Mock for `handle_create_post`.

        The route under test (`POST /posts`) reads `id` off the handler's
        return value to populate the response body and the `Location` /
        `HX-Redirect` headers. A `PostRead` (or any object with `.id`) suffices.
        """
        if post_read is None:
            post_read = cls.create_post_read()

        return {
            "src.api.routes.posts.handle_create_post": {
                "return_value_config": post_read
            }
        }

    @classmethod
    def create_post_edit_dependency_config(
        cls, post_read: PostRead = None
    ) -> Dict[str, Any]:
        """Mock for `handle_update_post`.

        The route under test (`PATCH /posts/{id}`) reads `id`, `title`, and
        `body` off the handler's return value and packs them into the JSON
        response, so a `PostRead` (or any object exposing those attributes) is
        sufficient.
        """
        if post_read is None:
            post_read = cls.create_post_read(title="patched title", body="patched body")

        return {
            "src.api.routes.posts.handle_update_post": {
                "return_value_config": post_read
            }
        }

    @classmethod
    def create_post_delete_dependency_config(cls) -> Dict[str, Any]:
        """Mock for `handle_delete_post`.

        The route under test (`DELETE /posts/{id}`) discards the handler
        return value and emits a 204 with `HX-Redirect: /posts`, so `None`
        is a valid mock return.
        """
        return {
            "src.api.routes.posts.handle_delete_post": {"return_value_config": None}
        }
