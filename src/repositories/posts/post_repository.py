from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Post

from ..base import BaseRepository


class PostRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_post_by_id(self, post_id: UUID) -> Post | None:
        """Retrieves a post by its ID. Per-kind detail relationships are
        eager-loaded via `lazy="selectin"` on the model."""
        return await self._get_by_id(Post, post_id)

    async def list_posts(self) -> Sequence[Post]:
        """Lists all posts, newest first. Detail relationships are eager-loaded."""
        return await self._list(select(Post).order_by(Post.created_at.desc()))
