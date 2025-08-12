from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Post
from src.schemas.post import PostType

from .base import BaseRepository


class PostRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def create_post(
        self, title: str, content: str, post_type: PostType, created_by_user_id: UUID
    ) -> Post:
        """Creates a new post."""
        post = Post(
            title=title,
            content=content,
            post_type=post_type,
            created_by_user_id=created_by_user_id,
        )
        self.session.add(post)
        await self.session.flush()
        await self.session.refresh(post)
        return post

    async def get_post_by_id(self, post_id: UUID) -> Post | None:
        """Retrieves a post by its ID."""
        stmt = select(Post).filter(Post.id == post_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_posts(
        self,
        *,
        post_type: PostType | None = None,
        created_by_user_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Post]:
        """Lists posts with optional filtering.

        Args:
            post_type: If provided, only returns posts of this type.
            created_by_user_id: If provided, only returns posts created by this user.
            limit: Maximum number of posts to return.
            offset: Number of posts to skip.
        """
        stmt = select(Post)

        if post_type:
            stmt = stmt.filter(Post.post_type == post_type)

        if created_by_user_id:
            stmt = stmt.filter(Post.created_by_user_id == created_by_user_id)

        stmt = stmt.order_by(Post.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_post(
        self, post_id: UUID, title: str | None = None, content: str | None = None
    ) -> Post | None:
        """Updates a post's title and/or content."""
        post = await self.get_post_by_id(post_id)
        if not post:
            return None

        if title is not None:
            post.title = title
        if content is not None:
            post.content = content

        await self.session.flush()
        await self.session.refresh(post)
        return post

    async def delete_post(self, post_id: UUID) -> bool:
        """Deletes a post by its ID. Returns True if deleted, False if not found."""
        post = await self.get_post_by_id(post_id)
        if not post:
            return False

        await self.session.delete(post)
        await self.session.flush()
        return True
