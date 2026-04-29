from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Post

from .base import BaseRepository


class PostRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_post_by_id(self, post_id: UUID) -> Post | None:
        """Retrieves a post by its ID."""
        stmt = select(Post).filter(Post.id == post_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_posts(self) -> Sequence[Post]:
        """Lists all posts, newest first."""
        stmt = select(Post).order_by(Post.created_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create_post(self, post: Post) -> Post:
        """Persists a new post and flushes; the caller commits."""
        self.session.add(post)
        await self.session.flush()
        await self.session.refresh(post)
        return post
