from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import with_polymorphic

from src.models import ClientReferral, Post, ProviderAvailability

from .base import BaseRepository

# Polymorphic selectable that pre-joins every kind's child table — used for
# the unified timeline so each row materializes as the right subclass instance
# without N+1 lazy loads. Add new kinds here when they're introduced.
_POLYMORPHIC_POST = with_polymorphic(Post, [ClientReferral, ProviderAvailability])


class PostRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_post_by_id(self, post_id: UUID) -> Post | None:
        """Retrieves a post by its ID, materialized as its kind-specific subclass."""
        stmt = select(_POLYMORPHIC_POST).filter(_POLYMORPHIC_POST.id == post_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_posts(self) -> Sequence[Post]:
        """Lists all posts (every kind), newest first.

        Uses `with_polymorphic` so each row comes back as the matching subclass
        instance with its child-table columns already loaded.
        """
        stmt = select(_POLYMORPHIC_POST).order_by(_POLYMORPHIC_POST.created_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create_post(self, post: Post) -> Post:
        """Persists a new post (any kind subclass) and flushes; the caller commits."""
        self.session.add(post)
        await self.session.flush()
        await self.session.refresh(post)
        return post

    async def delete_post(self, post: Post) -> None:
        """Deletes a post and flushes; the caller commits.

        The child row in the kind-specific table cascades via the FK ON DELETE.
        """
        await self.session.delete(post)
        await self.session.flush()
