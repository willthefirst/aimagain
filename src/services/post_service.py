import logging
from typing import Sequence
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from src.models import Post, User
from src.repositories.post_repository import PostRepository
from src.schemas.post import PostCreateRequest, PostType, PostUpdateRequest

from .exceptions import DatabaseError, ServiceError

logger = logging.getLogger(__name__)


class PostService:
    def __init__(self, post_repository: PostRepository):
        self.post_repo = post_repository

    async def create_post(self, request: PostCreateRequest, creator: User) -> Post:
        """Creates a new post."""
        try:
            return await self.post_repo.create_post(
                title=request.title,
                content=request.content,
                post_type=request.post_type,
                created_by_user_id=creator.id,
            )
        except SQLAlchemyError as e:
            logger.error(
                f"Database error creating post for user {creator.id}: {e}",
                exc_info=True,
            )
            raise DatabaseError("Failed to create post due to a database error.")
        except Exception as e:
            logger.error(
                f"Unexpected error creating post for user {creator.id}: {e}",
                exc_info=True,
            )
            raise ServiceError("An unexpected error occurred while creating post.")

    async def get_post(self, post_id: UUID) -> Post | None:
        """Retrieves a post by its ID."""
        try:
            return await self.post_repo.get_post_by_id(post_id)
        except SQLAlchemyError as e:
            logger.error(
                f"Database error fetching post {post_id}: {e}",
                exc_info=True,
            )
            raise DatabaseError("Failed to fetch post due to a database error.")
        except Exception as e:
            logger.error(
                f"Unexpected error fetching post {post_id}: {e}",
                exc_info=True,
            )
            raise ServiceError("An unexpected error occurred while fetching post.")

    async def list_posts(
        self,
        *,
        post_type: PostType | None = None,
        created_by_user_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Post]:
        """Lists posts with optional filtering."""
        try:
            return await self.post_repo.list_posts(
                post_type=post_type,
                created_by_user_id=created_by_user_id,
                limit=limit,
                offset=offset,
            )
        except SQLAlchemyError as e:
            logger.error(
                f"Database error listing posts: {e}",
                exc_info=True,
            )
            raise DatabaseError("Failed to list posts due to a database error.")
        except Exception as e:
            logger.error(
                f"Unexpected error listing posts: {e}",
                exc_info=True,
            )
            raise ServiceError("An unexpected error occurred while listing posts.")

    async def update_post(
        self, post_id: UUID, request: PostUpdateRequest, user: User
    ) -> Post | None:
        """Updates a post. Only the creator can update their posts."""
        try:
            # First check if the post exists and if the user owns it
            post = await self.post_repo.get_post_by_id(post_id)
            if not post:
                return None

            if post.created_by_user_id != user.id:
                logger.warning(
                    f"User {user.id} attempted to update post {post_id} they don't own"
                )
                raise ServiceError("You can only update your own posts.")

            return await self.post_repo.update_post(
                post_id=post_id, title=request.title, content=request.content
            )
        except ServiceError:
            # Re-raise service errors (like permission denied)
            raise
        except SQLAlchemyError as e:
            logger.error(
                f"Database error updating post {post_id} for user {user.id}: {e}",
                exc_info=True,
            )
            raise DatabaseError("Failed to update post due to a database error.")
        except Exception as e:
            logger.error(
                f"Unexpected error updating post {post_id} for user {user.id}: {e}",
                exc_info=True,
            )
            raise ServiceError("An unexpected error occurred while updating post.")

    async def delete_post(self, post_id: UUID, user: User) -> bool:
        """Deletes a post. Only the creator can delete their posts."""
        try:
            # First check if the post exists and if the user owns it
            post = await self.post_repo.get_post_by_id(post_id)
            if not post:
                return False

            if post.created_by_user_id != user.id:
                logger.warning(
                    f"User {user.id} attempted to delete post {post_id} they don't own"
                )
                raise ServiceError("You can only delete your own posts.")

            return await self.post_repo.delete_post(post_id)
        except ServiceError:
            # Re-raise service errors (like permission denied)
            raise
        except SQLAlchemyError as e:
            logger.error(
                f"Database error deleting post {post_id} for user {user.id}: {e}",
                exc_info=True,
            )
            raise DatabaseError("Failed to delete post due to a database error.")
        except Exception as e:
            logger.error(
                f"Unexpected error deleting post {post_id} for user {user.id}: {e}",
                exc_info=True,
            )
            raise ServiceError("An unexpected error occurred while deleting post.")
