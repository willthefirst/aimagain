from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import NoteDetail, Post

from .base import BaseRepository


class PostRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_post_by_id(self, post_id: UUID) -> Post | None:
        """Retrieves a post by its ID. The note_detail relationship is
        eager-loaded via `lazy="selectin"` on the model."""
        stmt = select(Post).filter(Post.id == post_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_posts(self) -> Sequence[Post]:
        """Lists all posts, newest first. note_detail is eager-loaded."""
        stmt = select(Post).order_by(Post.created_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create_post(self, post: Post, detail: NoteDetail) -> Post:
        """Persists a new post + its note detail in one flush; the caller
        commits.

        The detail's `post_id` is wired up via the `note_detail`
        relationship, so callers pass the unattached detail and we attach
        it here. CASCADE on the FK keeps lifetimes locked together.
        """
        post.note_detail = detail
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
        """Mutates only the fields that were provided and flushes; the caller
        commits. `title`/`body` live on the note detail."""
        if title is not None:
            post.note_detail.title = title
        if body is not None:
            post.note_detail.body = body
        self.session.add(post)
        await self.session.flush()
        await self.session.refresh(post)
        return post

    async def delete_post(self, post: Post) -> None:
        """Deletes a post and flushes; the caller commits. The note detail
        is removed by `ON DELETE CASCADE` on the FK."""
        await self.session.delete(post)
        await self.session.flush()
