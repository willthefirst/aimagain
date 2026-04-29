"""Factory for consistent mock data and dependency-override configs.

Each `create_*_dependency_config()` returns a mapping of fully-qualified
handler paths to mock configuration. The provider server fixture
(`tests/test_contract/conftest.py::provider_server`) consumes this mapping to
monkey-patch business-logic handlers, so Pact verification exercises only the
route layer.
"""

from typing import Any, Dict
from uuid import uuid4

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
