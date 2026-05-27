"""Verification override — one per (selected) clinician; idempotent on PK.

Generic generator would pick a random clinician per row; we want each
Verification to FK to a *distinct* clinician so the directory's "has
verification" filter exercises both populated and empty cases.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import Clinician, Verification
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
    clinicians: list[Clinician] = pool.all("clinicians")
    target = min(counts.VERIFICATION_COUNT, len(clinicians))
    out: list[Verification] = []
    for i in range(target):
        clinician = clinicians[i]
        row = Verification(
            id=deterministic_uuid("Verification", i),
            clinician_id=clinician.id,
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
