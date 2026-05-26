"""UserFavorite override — M:N with `(user_id, clinician_id)` unique.

Generic generator would pick random pairs and could violate the
UNIQUE constraint on collision. This override generates distinct
pairs by indexing (user, clinician) with co-prime strides.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import Clinician, User, UserFavorite

from .. import counts
from ..generators import SeedPool
from ..rng import SeededRandom, deterministic_uuid
from . import register


@register(UserFavorite)
async def generate_favorites(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[UserFavorite]:
    users: list[User] = pool.all("users")
    clinicians: list[Clinician] = pool.all("clinicians")
    seen: set[tuple] = set()
    out: list[UserFavorite] = []
    target = min(counts.FAVORITE_COUNT, len(users) * len(clinicians))
    i = 0
    # Deterministic walk via (user_index, clinician_index) with co-prime
    # strides keeps pairs distinct without rejection-sampling.
    while len(out) < target and i < target * 4:
        u = users[(i * 7) % len(users)]
        c = clinicians[(i * 11) % len(clinicians)]
        key = (u.id, c.id)
        i += 1
        if key in seen:
            continue
        seen.add(key)
        row = UserFavorite(
            id=deterministic_uuid("UserFavorite", len(out)),
            user_id=u.id,
            clinician_id=c.id,
        )
        await session.merge(row)
        out.append(row)
    await session.commit()
    return out
