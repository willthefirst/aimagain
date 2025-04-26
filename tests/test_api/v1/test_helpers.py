import uuid
from typing import Optional, Union
from uuid import UUID  # Import UUID

# Need ORM models
from app.models import User


def create_test_user(
    id: Optional[UUID] = None,
    username: Optional[str] = None,
    email: Optional[str] = None,
    hashed_password: Optional[str] = None,
    is_online: bool = True,
    is_active: bool = True,  # Added fastapi-users default
    is_superuser: bool = False,  # Added fastapi-users default
    is_verified: bool = True,  # Added fastapi-users default
) -> User:
    """Creates a User instance with default values for testing."""
    unique_suffix = uuid.uuid4()
    return User(
        id=id or unique_suffix,
        username=username or f"testuser_{unique_suffix}",
        email=email or f"test_{unique_suffix}@example.com",
        hashed_password=hashed_password or f"password_{unique_suffix}",
        is_online=is_online,
        is_active=is_active,
        is_superuser=is_superuser,
        is_verified=is_verified,
    )
