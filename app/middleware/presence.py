import logging
from datetime import datetime, timezone
from typing import Optional

import jwt
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger(__name__)


class PresenceMiddleware(BaseHTTPMiddleware):
    """Updates user last_active_at for all successful authenticated requests"""

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

            # Update last_active_at
            await self._do_presence_update(user_id)

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
            from app.core.config import settings

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

    async def _do_presence_update(self, user_id: str):
        """Actually update the database"""
        try:
            # Get database session from dependency injection
            import uuid

            from sqlalchemy import update

            from app.db import get_db_session
            from app.models import User

            # Convert string user_id to UUID
            user_uuid = uuid.UUID(user_id)

            # Get the actual dependency function (respects overrides in tests)
            from app.main import app

            db_session_func = app.dependency_overrides.get(
                get_db_session, get_db_session
            )

            # Get a database session
            async for session in db_session_func():
                try:
                    # Update the user's last_active_at timestamp
                    stmt = (
                        update(User)
                        .where(User.id == user_uuid)
                        .values(last_active_at=datetime.now(timezone.utc))
                    )
                    result = await session.execute(stmt)
                    await session.commit()
                    break  # Exit the async generator loop
                except Exception as e:
                    await session.rollback()
                    logger.warning(
                        f"Database error updating presence for user {user_id}: {e}"
                    )
                    raise

        except Exception as e:
            logger.warning(f"Failed to update presence for user {user_id}: {e}")
            # Don't re-raise - we don't want to break the main request


# Helper function for testing
async def update_user_presence(user_id: str):
    """Helper function to update user presence - used for testing"""
    middleware = PresenceMiddleware(None)
    await middleware._do_presence_update(user_id)
