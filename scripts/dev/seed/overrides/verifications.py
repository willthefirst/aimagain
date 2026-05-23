"""Verification override — one per (selected) provider; idempotent on PK.

Generic generator would pick a random provider per row; we want each
Verification to FK to a *distinct* provider so the directory's "has
verification" filter exercises both populated and empty cases.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import Provider, Verification
from src.domain.models.enums import VERIFICATION_STATUSES

from .. import counts
from ..generators import SeedPool
from ..rng import SeededRandom, deterministic_uuid
from ..vocab import JSON_LIST_SOURCE
from . import register


@register(Verification)
async def generate_verifications(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[Verification]:
    providers: list[Provider] = pool.all("providers")
    target = min(counts.VERIFICATION_COUNT, len(providers))
    out: list[Verification] = []
    for i in range(target):
        provider = providers[i]
        row = Verification(
            id=deterministic_uuid("Verification", i),
            provider_id=provider.id,
            status=rng.round_robin(VERIFICATION_STATUSES, i),
            flags=rng.nullable_subset(
                JSON_LIST_SOURCE["flags"], min_size=0, max_size=3, p_empty=0.4
            ),
            # Most rows have a null payload (NPPES wasn't queried or
            # the call failed); a slice carries a minimal stub so the
            # nullable-coverage test sees both samples.
            nppes_result=(None if rng.bool(0.6) else {"npi": "0000000000"}),
            oig_match=rng.bool(0.05),
            name_match_score=(None if rng.bool(0.2) else round(rng.random(), 3)),
        )
        await session.merge(row)
        out.append(row)
    await session.commit()
    return out
