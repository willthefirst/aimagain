from typing import Sequence

from sqlalchemy import select

from src.framework.base_repository import BaseRepository
from src.models import Post


class PostRepository(BaseRepository):
    async def list_posts(self) -> Sequence[Post]:
        """Lists all posts, newest first. Detail relationships are eager-loaded."""
        return await self._list(select(Post).order_by(Post.created_at.desc()))
