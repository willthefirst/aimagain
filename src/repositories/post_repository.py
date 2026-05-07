from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    KIND_BY_DETAIL_MODEL,
    REGISTERED_KINDS,
    ClientReferralDetail,
    Post,
    ProviderAvailabilityDetail,
)

from .base import BaseRepository

PostDetail = ClientReferralDetail | ProviderAvailabilityDetail


def _attach_detail(post: Post, detail: PostDetail) -> None:
    """Wire a fresh detail row up to its parent on the right relationship.

    The detail-class-to-relationship mapping is the registry in
    `src/models/post_kinds.py` — adding a new kind there is enough."""
    spec = KIND_BY_DETAIL_MODEL.get(type(detail))
    if spec is None:
        raise TypeError(f"unsupported detail type: {type(detail).__name__}")
    setattr(post, spec.detail_relationship, detail)


class PostRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_post_by_id(self, post_id: UUID) -> Post | None:
        """Retrieves a post by its ID. Per-kind detail relationships are
        eager-loaded via `lazy="selectin"` on the model."""
        return await self._get_by_id(Post, post_id)

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
        return await self._persist_new(post)

    async def update_post(self, post: Post, **detail_fields: Any) -> Post:
        """Mutates the per-kind detail fields that were provided and flushes;
        the caller commits.

        `detail_fields` is keyed by the field names on the post's
        per-kind detail row (the `KindSpec.detail_fields` for `post.kind`
        in `src/models/post_kinds.py`). Fields whose value is `None` and
        fields that don't belong to the post's kind are silently skipped
        — the calling logic layer is responsible for rejecting cross-kind
        writes at the route boundary with a 400.

        `post.kind` is intentionally not writable here: kind is part of
        the resource identity and is fixed at create time.
        """
        spec = REGISTERED_KINDS[post.kind]
        detail = getattr(post, spec.detail_relationship)
        for field_name, value in detail_fields.items():
            if value is None or field_name not in spec.detail_fields:
                continue
            setattr(detail, field_name, value)
        self.session.add(post)
        await self.session.flush()
        await self.session.refresh(post)
        return post

    async def delete_post(self, post: Post) -> None:
        """Deletes a post and flushes; the caller commits. The per-kind
        detail row is removed by `ON DELETE CASCADE` on the FK."""
        await self._delete(post)
