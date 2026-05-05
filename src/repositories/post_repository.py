from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    ClientReferralDetail,
    NoteDetail,
    Post,
    ProviderAvailabilityDetail,
)

from .base import BaseRepository

PostDetail = NoteDetail | ClientReferralDetail | ProviderAvailabilityDetail


def _attach_detail(post: Post, detail: PostDetail) -> None:
    """Wire a fresh detail row up to its parent on the right relationship.

    Adding a new `kind` means adding its detail class here.
    """
    if isinstance(detail, NoteDetail):
        post.note_detail = detail
    elif isinstance(detail, ClientReferralDetail):
        post.client_referral_detail = detail
    elif isinstance(detail, ProviderAvailabilityDetail):
        post.provider_availability_detail = detail
    else:
        raise TypeError(f"unsupported detail type: {type(detail).__name__}")


class PostRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_post_by_id(self, post_id: UUID) -> Post | None:
        """Retrieves a post by its ID. Per-kind detail relationships are
        eager-loaded via `lazy="selectin"` on the model."""
        stmt = select(Post).filter(Post.id == post_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_posts(self) -> Sequence[Post]:
        """Lists all posts, newest first. Detail relationships are eager-loaded."""
        stmt = select(Post).order_by(Post.created_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create_post(self, post: Post, detail: PostDetail) -> Post:
        """Persists a new post + its per-kind detail in one flush; the
        caller commits.

        The detail's `post_id` is wired up via the appropriate
        `*_detail` relationship (chosen by `_attach_detail` based on the
        detail's type). CASCADE on the FK keeps lifetimes locked together.
        """
        _attach_detail(post, detail)
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
        description: str | None = None,
        practice_name: str | None = None,
    ) -> Post:
        """Mutates only the per-kind fields that were provided and flushes;
        the caller commits.

        - `title` / `body` are written to `post.note_detail` (kind='note').
        - `description` is written to `post.client_referral_detail`
          (kind='client_referral').
        - `practice_name` is written to `post.provider_availability_detail`
          (kind='provider_availability').

        `post.kind` is intentionally not a parameter and never written by
        this method — kind is part of the resource identity and is fixed
        at create time. Cross-kind writes (e.g. `title` on a
        client_referral) are silently skipped here; the calling logic
        layer rejects them at the route boundary with a 400.
        """
        if post.kind == "note":
            if title is not None:
                post.note_detail.title = title
            if body is not None:
                post.note_detail.body = body
        elif post.kind == "client_referral":
            if description is not None:
                post.client_referral_detail.description = description
        elif post.kind == "provider_availability":
            if practice_name is not None:
                post.provider_availability_detail.practice_name = practice_name
        self.session.add(post)
        await self.session.flush()
        await self.session.refresh(post)
        return post

    async def delete_post(self, post: Post) -> None:
        """Deletes a post and flushes; the caller commits. The per-kind
        detail row is removed by `ON DELETE CASCADE` on the FK."""
        await self.session.delete(post)
        await self.session.flush()
