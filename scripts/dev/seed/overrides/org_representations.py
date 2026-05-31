"""OrgRepresentation seed override.

Round-robins every CHECK-vocabulary value across role, authority_method,
and authority_status. The `(user_id, org_id)` unique constraint forces
us to walk distinct pairs — we take the first
`ORG_REPRESENTATION_COUNT` (user, org) tuples and assign one row each.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import Organization, OrgRepresentation, User
from src.domain.models.enums import (
    AUTHORITY_METHODS,
    AUTHORITY_STATUSES,
    ORG_REPRESENTATION_ROLES,
)

from .. import counts
from ..generators import SeedPool
from ..rng import SeededRandom, deterministic_uuid
from . import register


@register(OrgRepresentation)
async def generate_org_representations(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[OrgRepresentation]:
    users: list[User] = pool.all("users")
    orgs: list[Organization] = pool.all("organizations")
    if not users or not orgs:
        return []

    target = min(counts.ORG_REPRESENTATION_COUNT, len(users) * len(orgs))
    out: list[OrgRepresentation] = []
    for i in range(target):
        # Distinct (user, org) pair by index: stride users by 1 and
        # orgs by a prime to avoid clumping on small datasets.
        user = users[i % len(users)]
        org = orgs[(i * 3) % len(orgs)]
        status = rng.round_robin(AUTHORITY_STATUSES, i)
        # `archived_at` populated for a slice so the nullable column
        # coverage test sees both buckets without making active rows
        # collide on the unique constraint (only some statuses get
        # archived; the unique constraint still permits one
        # `archived_at IS NULL` per (user, org) — we walk distinct
        # pairs above).
        archived = (
            rng.date_within_years(years_back=1, years_forward=0)
            if status == "rejected"
            else None
        )
        row = OrgRepresentation(
            id=deterministic_uuid("OrgRepresentation", i),
            user_id=user.id,
            org_id=org.id,
            role=rng.round_robin(ORG_REPRESENTATION_ROLES, i),
            authority_method=rng.round_robin(AUTHORITY_METHODS, i),
            authority_status=status,
            approved_by=(users[(i + 7) % len(users)].id if rng.bool(0.3) else None),
            archived_at=archived,
        )
        await session.merge(row)
        out.append(row)
    await session.commit()
    return out
