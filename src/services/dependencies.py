from .provider import ServiceProvider
from .user_service import UserService


def get_user_service() -> UserService:
    """Provides an instance of the UserService."""
    return ServiceProvider.get_service(UserService)
