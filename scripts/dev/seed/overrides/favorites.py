"""UserFavorite override — M:N with `(user_id, provider_id)` unique.

Generic generator would pick random pairs and could violate the
UNIQUE constraint on collision. This override generates distinct
pairs by indexing (user, provider) with co-prime strides.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import Provider, User, UserFavorite

from .. import counts
from ..generators import SeedPool
from ..rng import SeededRandom, deterministic_uuid
from . import register


@register(UserFavorite)
async def generate_favorites(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[UserFavorite]:
    users: list[User] = pool.all("users")
    providers: list[Provider] = pool.all("providers")
    seen: set[tuple] = set()
    out: list[UserFavorite] = []
    target = min(counts.FAVORITE_COUNT, len(users) * len(providers))
    i = 0
    # Deterministic walk via (user_index, provider_index) with co-prime
    # strides keeps pairs distinct without rejection-sampling.
    while len(out) < target and i < target * 4:
        u = users[(i * 7) % len(users)]
        p = providers[(i * 11) % len(providers)]
        key = (u.id, p.id)
        i += 1
        if key in seen:
            continue
        seen.add(key)
        row = UserFavorite(
            id=deterministic_uuid("UserFavorite", len(out)),
            user_id=u.id,
            provider_id=p.id,
        )
        await session.merge(row)
        out.append(row)
    await session.commit()
    return out
