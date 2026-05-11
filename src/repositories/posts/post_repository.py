from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import POST_KINDS, Post

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

    async def update_post(self, post: Post, **detail_fields: Any) -> Post:
        """Mutates the per-kind detail fields that were provided and flushes;
        the caller commits.

        `detail_fields` is keyed by the field names on the post's
        per-kind detail row (the `PostKindSpec.detail_fields` for `post.kind`
        in `src/models/posts/post_kinds.py`). Fields whose value is `None` and
        fields that don't belong to the post's kind are silently skipped
        — the calling logic layer is responsible for rejecting cross-kind
        writes at the route boundary with a 400.

        `post.kind` is intentionally not writable here: kind is part of
        the resource identity and is fixed at create time.
        """
        spec = POST_KINDS[post.kind]
        detail = getattr(post, spec.detail_relationship)
        for field_name, value in detail_fields.items():
            if value is None or field_name not in spec.detail_fields:
                continue
            setattr(detail, field_name, value)
        self.session.add(post)
        await self.session.flush()
        await self.session.refresh(post)
        return post
