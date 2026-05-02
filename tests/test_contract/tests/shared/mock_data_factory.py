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

from src.schemas.post import ClientReferralRead
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
        owner_id: UUID = None,
        description: str = "stub description",
    ) -> ClientReferralRead:
        """Returns a `client_referral` read schema. The routes under test only
        read `.id` off the return, so a single kind suffices for both create
        and edit mocks."""
        now = datetime.now(timezone.utc)
        return ClientReferralRead(
            id=post_id or cls.MOCK_POST_ID,
            kind="client_referral",
            owner_id=owner_id or cls.MOCK_POST_OWNER_ID,
            location_city="Northampton",
            location_state="MA",
            location_zip="01060",
            location_in_person="yes",
            location_virtual="please_contact",
            desired_times=["monday_morning"],
            client_dem_ages="adults_25_64",
            language_preferred="no",
            description=description,
            services=["psychotherapy"],
            services_psychotherapy_modality="DBT",
            insurance="in_network",
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def create_post_create_dependency_config(
        cls, post_read: ClientReferralRead = None
    ) -> Dict[str, Any]:
        """Mock for `handle_create_post`.

        The route under test (`POST /posts`) reads `id` off the handler's
        return value to populate the response body and the `Location` /
        `HX-Redirect` headers. Any object exposing `.id` suffices.
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
        cls, post_read: ClientReferralRead = None
    ) -> Dict[str, Any]:
        """Mock for `handle_update_post`.

        The route under test (`PATCH /posts/{id}`) reads `id` off the handler's
        return value and packs it into the JSON response, so any object
        exposing `.id` is sufficient.
        """
        if post_read is None:
            post_read = cls.create_post_read(description="patched description")

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
