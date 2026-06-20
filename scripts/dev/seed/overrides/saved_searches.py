"""SavedSearch override — the default searches every user starts with.

The generic generator would emit random one-off saved searches with
placeholder names and empty filters. That's not representative: in the
real app every user begins with the two defaults (openings + referrals)
seeded at registration. This override reproduces that by routing each
seeded user through the same `seed_default_saved_searches` helper the
registration hook uses — so dev data matches production behavior and
there's one source of truth for what the defaults are.

The helper is name-idempotent (skips a default the user already has),
which doubles as the seed's rerun-idempotency: a second `dev seed`
adds nothing.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.logic.saved_searches.defaults import seed_default_saved_searches
from src.domain.models import SavedSearch, User

from ..generators import SeedPool
from ..rng import SeededRandom
from . import register


@register(SavedSearch)
async def generate_saved_searches(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[SavedSearch]:
    users: list[User] = pool.all("users")
    for u in users:
        await seed_default_saved_searches(session, u.id)
    # Return the rows so the runner can add them to the pool, matching
    # the override contract (other overrides return what they inserted).
    return list((await session.execute(select(SavedSearch))).scalars().all())
