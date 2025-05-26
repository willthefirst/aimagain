import logging
import uuid
from typing import AsyncGenerator, Callable, Optional

import jwt
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings

logger = logging.getLogger(__name__)


class PresenceMiddleware(BaseHTTPMiddleware):
    """Updates user last_active_at and is_online for all successful authenticated requests"""

    def __init__(
        self,
        app,
        session_factory: Callable[[], AsyncGenerator[AsyncSession, None]],
    ):
        super().__init__(app)
        self.session_factory = session_factory

    async def dispatch(self, request: Request, call_next):
        # Process the request first
        response = await call_next(request)

        # Only update presence after successful requests (2xx and 3xx status codes)
        if 200 <= response.status_code < 400:
            await self._update_user_presence(request)

        return response

    async def _update_user_presence(self, request: Request):
        """Update user's last_active_at timestamp"""
        try:
            # Get user ID from JWT token in cookie
            user_id = await self._get_user_id_from_request(request)
            if not user_id:
                return

            # Get presence service and update presence
            await self._do_presence_update(user_id, request)

        except Exception as e:
            # Never let presence updates break the main request
            logger.warning(f"Failed to update user presence: {e}")

    async def _get_user_id_from_request(self, request: Request) -> Optional[str]:
        """Extract user ID from JWT token in cookies"""
        try:
            # Get the authentication cookie
            auth_cookie = request.cookies.get("fastapiusersauth")
            if not auth_cookie:
                return None

            # Decode the JWT token to get user ID
            # Try decoding with minimal validation first
            try:
                payload = jwt.decode(
                    auth_cookie,
                    settings.SECRET,
                    algorithms=["HS256"],
                    options={"verify_aud": False},  # Skip audience verification
                )
            except jwt.InvalidTokenError:
                # If that fails, try without any verification (for debugging)
                payload = jwt.decode(auth_cookie, options={"verify_signature": False})
                # Now try with proper verification but no audience check
                payload = jwt.decode(
                    auth_cookie,
                    settings.SECRET,
                    algorithms=["HS256"],
                    options={"verify_aud": False},
                )

            user_id = payload.get("sub")
            return user_id

        except Exception as e:
            logger.debug(f"Could not extract user ID from request: {e}")
            return None

    async def _do_presence_update(self, user_id: str, request: Request):
        """Update presence using the service"""
        try:
            # Convert string user_id to UUID
            user_uuid = uuid.UUID(user_id)

            # Get the appropriate session factory
            # Check if there are dependency overrides (for testing)
            session_factory = self.session_factory
            if hasattr(request.app, "dependency_overrides"):
                from app.db import get_db_session

                overridden_factory = request.app.dependency_overrides.get(
                    get_db_session
                )
                if overridden_factory:
                    session_factory = overridden_factory

            # Get database session using the session factory
            async for session in session_factory():
                try:
                    # Create repository and service
                    from app.repositories.user_repository import UserRepository
                    from app.services.presence_service import PresenceService

                    user_repo = UserRepository(session)
                    presence_service = PresenceService(user_repo)

                    # Update presence
                    await presence_service.update_user_presence(user_uuid)
                    break
                except Exception as e:
                    logger.warning(f"Error updating presence for user {user_id}: {e}")
                    raise

        except Exception as e:
            logger.warning(f"Failed to update presence for user {user_id}: {e}")
            # Don't re-raise - we don't want to break the main request


async def update_all_users_online_status(session=None):
    """Update is_online status for all users based on their last_active_at timestamp"""
    try:
        if session:
            # For testing - create service directly with session
            from app.repositories.user_repository import UserRepository
            from app.services.presence_service import PresenceService

            user_repo = UserRepository(session)
            presence_service = PresenceService(user_repo)
            await presence_service.update_all_users_online_status(
                settings.ONLINE_TIMEOUT_MINUTES
            )
        else:
            # Use default session factory
            from app.db import get_db_session
            from app.repositories.user_repository import UserRepository
            from app.services.presence_service import PresenceService

            async for session in get_db_session():
                try:
                    user_repo = UserRepository(session)
                    presence_service = PresenceService(user_repo)
                    await presence_service.update_all_users_online_status(
                        settings.ONLINE_TIMEOUT_MINUTES
                    )
                    break  # Exit the async generator loop
                except Exception as e:
                    logger.warning(f"Error updating all users online status: {e}")
                    raise

    except Exception as e:
        logger.warning(f"Failed to update all users online status: {e}")
        raise
