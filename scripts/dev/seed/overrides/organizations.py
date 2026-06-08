"""Organization override — flat directory of standalone orgs.

Each org is its own row, owned by a randomly-picked seeded user.
NPI / verification state are round-robined across the dataset so every
CHECK-vocabulary value (`NPI_MATCH_STATUSES`) appears.

Idempotency: deterministic UUIDs by index; `session.merge` for upsert.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import Organization, User
from src.domain.models.enums import NPI_MATCH_STATUSES

from .. import counts
from ..generators import SeedPool
from ..rng import SeededRandom, deterministic_uuid
from ..vocab import COLUMN_VOCAB, practice_name
from . import register


def _stable_id(index: int):
    return deterministic_uuid("Organization", index)


def _verification_kwargs(rng: SeededRandom, index: int) -> dict:
    """Round-robin `NPI_MATCH_STATUSES` so every CHECK-vocabulary value
    appears across the org dataset. Type-2 NPI presence + the `matched`
    bucket together drive `org_verified` and the `verified_at` /
    `authorized_official_name` columns. The non-matched rows still
    populate `verified_at` / `authorized_official_name` sometimes so
    nullable coverage stays balanced."""
    match_status = rng.round_robin(NPI_MATCH_STATUSES, index)
    org_verified = match_status == "matched"
    has_npi = match_status != "none"
    verified_ts = (
        rng.date_within_years(years_back=1, years_forward=0) if org_verified else None
    )
    return {
        "npi": COLUMN_VOCAB["npi"](rng, index) if has_npi else None,
        "npi_match_status": match_status,
        "org_verified": org_verified,
        "verified_at": verified_ts,
        "authorized_official_name": (
            f"{COLUMN_VOCAB['first_name'](rng, index)} {COLUMN_VOCAB['last_name'](rng, index)}"
            if org_verified
            else None
        ),
    }


@register(Organization)
async def generate_organizations(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[Organization]:
    users: list[User] = pool.all("users")
    if not users:
        raise RuntimeError("Organizations require users; seed users first.")

    out: list[Organization] = []
    for index in range(counts.ORGANIZATION_COUNT):
        oid = _stable_id(index)
        row = Organization(
            id=oid,
            name=practice_name(rng, index),
            owner_id=rng.choice(users).id,
            **_verification_kwargs(rng, index),
        )
        await session.merge(row)
        out.append(row)

    await session.commit()
    return out
