from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select

from src.domain.models import Clinician, UserFavorite
from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import register_repository


class UserFavoriteRepository(BaseRepository):
    async def get_by_pair(
        self, *, user_id: UUID, clinician_id: UUID
    ) -> UserFavorite | None:
        stmt = select(UserFavorite).filter(
            UserFavorite.user_id == user_id,
            UserFavorite.clinician_id == clinician_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def add_favorite(self, *, user_id: UUID, clinician_id: UUID) -> UserFavorite:
        return await self._persist_new(
            UserFavorite(user_id=user_id, clinician_id=clinician_id)
        )

    async def delete_favorite(self, favorite: UserFavorite) -> None:
        await self._delete(favorite)

    async def list_favorited_clinicians(
        self,
        user_id: UUID,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> Sequence[Clinician]:
        """Return the clinicians a user has favorited, newest-favoriting first."""
        stmt = (
            select(Clinician)
            .join(UserFavorite, UserFavorite.clinician_id == Clinician.id)
            .filter(UserFavorite.user_id == user_id)
            .order_by(UserFavorite.created_at.desc())
        )
        return await self._list(stmt, offset=offset, limit=limit)

    async def is_favorited(self, *, user_id: UUID, clinician_id: UUID) -> bool:
        return (
            await self.get_by_pair(user_id=user_id, clinician_id=clinician_id)
        ) is not None


get_user_favorite_repository = register_repository(UserFavoriteRepository)
