"""Program override — ensures nullable ``description`` coverage.

The generic generator seeds ``description`` with 0.2 null probability.
With only 12 program rows and a fixed RNG seed the deterministic
sequence can produce zero NULLs, failing the nullable-coverage test.
This override explicitly sets ``description=None`` for the first row
and populates the rest from vocab, guaranteeing both NULL and non-NULL
samples regardless of RNG state.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import Organization, Program, User
from src.domain.models.enums import US_STATES

from .. import counts
from ..generators import SeedPool
from ..rng import SeededRandom, deterministic_uuid
from ..vocab import INTAKE_SUBJECTS, program_name
from . import register


@register(Program)
async def generate_programs(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[Program]:
    users: list[User] = pool.all("users")
    orgs: list[Organization] = pool.all("organizations")
    if not users or not orgs:
        raise RuntimeError("Programs require users and organizations seeded first.")

    out: list[Program] = []
    for i in range(counts.PROGRAM_COUNT):
        # Row 0 explicitly has description=None to guarantee NULL coverage.
        # Row 0: description=None, no dates — guarantees NULL coverage.
        # Remaining rows: populate description and occasionally dates.
        if i == 0:
            description = None
            start_date = None
            end_date = None
        else:
            description = rng.choice(INTAKE_SUBJECTS)
            start_date = date(2025, 1 + (i % 12), 1) if i % 3 == 1 else None
            end_date = date(2025, 6 + (i % 6), 1) if i % 3 == 1 else None
        row = Program(
            id=deterministic_uuid("Program", i),
            owner_id=rng.choice(users).id,
            org_id=rng.choice(orgs).id,
            name=program_name(rng, i),
            description=description,
            state_preference=rng.choice(US_STATES) if rng.random() > 0.4 else None,
            start_date=start_date,
            end_date=end_date,
            accepting_referrals=rng.random() > 0.2,
        )
        await session.merge(row)
        out.append(row)

    await session.commit()
    return out
