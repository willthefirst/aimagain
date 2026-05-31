"""Verification override — one per (selected) clinician; idempotent on PK.

Generic generator would pick a random clinician per row; we want each
Verification to FK to a *distinct* clinician so the directory's "has
verification" filter exercises both populated and empty cases.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import Clinician, Organization, Verification
from src.domain.models.enums import (
    VERIFICATION_EVENT_TYPES,
    VERIFICATION_STATUSES,
    VERIFICATION_SUBJECT_TYPES,
)

from .. import counts
from ..generators import SeedPool
from ..rng import SeededRandom, deterministic_uuid
from ..vocab import JSON_LIST_SOURCE
from . import register


@register(Verification)
async def generate_verifications(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[Verification]:
    """Round-robin both `subject_type` values and the `event_type` vocab
    across the dataset so seed-coverage CHECKs pass. Every row picks a
    distinct subject (clinician or org) and the discriminator-shape
    invariant is honored by `_subject_kwargs(...)`."""
    clinicians: list[Clinician] = pool.all("clinicians")
    orgs: list[Organization] = pool.all("organizations")
    target = min(counts.VERIFICATION_COUNT, len(clinicians) + len(orgs))
    out: list[Verification] = []
    for i in range(target):
        subject_type = rng.round_robin(VERIFICATION_SUBJECT_TYPES, i)
        subject_kwargs = (
            {"clinician_id": clinicians[i % len(clinicians)].id, "org_id": None}
            if subject_type == "clinician"
            else {"clinician_id": None, "org_id": orgs[i % len(orgs)].id}
        )
        row = Verification(
            id=deterministic_uuid("Verification", i),
            subject_type=subject_type,
            event_type=rng.round_robin(VERIFICATION_EVENT_TYPES, i),
            status=rng.round_robin(VERIFICATION_STATUSES, i),
            flags=rng.nullable_subset(
                JSON_LIST_SOURCE["flags"], min_size=0, max_size=3, p_empty=0.4
            ),
            # Most rows have a null payload (NPPES wasn't queried or
            # the call failed); a slice carries a minimal stub so the
            # nullable-coverage test sees both samples.
            nppes_result=(None if rng.bool(0.6) else {"npi": "0000000000"}),
            evidence=(None if rng.bool(0.5) else {"note": "seed"}),
            oig_match=rng.bool(0.05),
            name_match_score=(None if rng.bool(0.2) else round(rng.random(), 3)),
            **subject_kwargs,
        )
        await session.merge(row)
        out.append(row)
    await session.commit()
    return out
