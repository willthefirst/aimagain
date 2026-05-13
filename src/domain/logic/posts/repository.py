from collections.abc import Sequence

from sqlalchemy import select

from src.domain.models import Post
from src.framework.persistence.base_repository import BaseRepository


class PostRepository(BaseRepository):
    """Posts-specific reads. Today this is only the `kind` filter on the
    list endpoint; future per-axis filters (state, age group, language,
    service, insurance posture) join through the polymorphic detail
    tables and will live here.
    """

    async def list_posts(self, *, kind: str | None = None) -> Sequence[Post]:
        stmt = select(Post)
        if kind is not None:
            stmt = stmt.filter(Post.kind == kind)
        stmt = stmt.order_by(Post.created_at.desc())
        return await self._list(stmt)
