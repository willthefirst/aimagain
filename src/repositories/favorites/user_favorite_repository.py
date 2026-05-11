from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select

from src.models import Provider, UserFavorite

from ..base import BaseRepository


class UserFavoriteRepository(BaseRepository):
    async def get_by_pair(
        self, *, user_id: UUID, provider_id: UUID
    ) -> UserFavorite | None:
        """Return the edge for `(user_id, provider_id)` if it exists, else
        `None`. Used to drive the idempotency of add/remove and the
        per-viewer `is_favorited` flag on provider detail."""
        stmt = select(UserFavorite).filter(
            UserFavorite.user_id == user_id,
            UserFavorite.provider_id == provider_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def add_favorite(self, *, user_id: UUID, provider_id: UUID) -> UserFavorite:
        """Persist a new edge. Caller is responsible for checking
        idempotency via `get_by_pair` first — passing a duplicate pair
        violates `uq_user_favorites_user_provider`."""
        return await self._persist_new(
            UserFavorite(user_id=user_id, provider_id=provider_id)
        )

    async def delete_favorite(self, favorite: UserFavorite) -> None:
        await self._delete(favorite)

    async def list_favorited_providers(self, user_id: UUID) -> Sequence[Provider]:
        """Return the providers a user has favorited, newest-favoriting
        first. Joined query (not two round-trips) so the listing page
        renders in one shot."""
        stmt = (
            select(Provider)
            .join(UserFavorite, UserFavorite.provider_id == Provider.id)
            .filter(UserFavorite.user_id == user_id)
            .order_by(UserFavorite.created_at.desc())
        )
        return await self._list(stmt)

    async def is_favorited(self, *, user_id: UUID, provider_id: UUID) -> bool:
        """True if this user has this provider favorited. Wrapper around
        `get_by_pair` for callers that only need the boolean."""
        return (
            await self.get_by_pair(user_id=user_id, provider_id=provider_id)
        ) is not None
