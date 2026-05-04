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

    async def update_post(
        self,
        post: Post,
        *,
        title: str | None = None,
        body: str | None = None,
    ) -> Post:
        """Mutates only the fields that were provided and flushes; the caller commits."""
        if title is not None:
            post.title = title
        if body is not None:
            post.body = body
        self.session.add(post)
        await self.session.flush()
        await self.session.refresh(post)
        return post

    async def delete_post(self, post: Post) -> None:
        """Deletes a post and flushes; the caller commits."""
        await self.session.delete(post)
        await self.session.flush()
