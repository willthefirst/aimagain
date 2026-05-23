"""Organization override — parent/child hierarchy.

The directory has self-referential org structure: a `health_system`
sits at the root, child clinics carry `parent_org_id` set and
`root_org_id` denormalized. The generic generator would happily set
both columns to random org IDs, breaking the invariant that
`root_org_id` is the transitive root of the parent chain.

This override:
  - Reserves the first `ORG_HIERARCHY_HEALTH_SYSTEM_ROOTS` slots
    for `health_system` roots (parent_org_id = NULL,
    root_org_id = self.id).
  - Attaches `ORG_HIERARCHY_CHILDREN_PER_ROOT` children per root
    (parent_org_id = root.id, root_org_id = root.id).
  - Generates remaining slots as standalone orgs (root = self,
    parent = NULL), round-robining `ORGANIZATION_TYPES`.

Idempotency: deterministic UUIDs by index; `session.merge` for upsert.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import Organization, User
from src.domain.models.enums import ORGANIZATION_TYPES

from .. import counts
from ..generators import SeedPool
from ..rng import SeededRandom, deterministic_uuid
from ..vocab import practice_name
from . import register


def _stable_id(index: int):
    return deterministic_uuid("Organization", index)


@register(Organization)
async def generate_organizations(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[Organization]:
    users: list[User] = pool.all("users")
    if not users:
        raise RuntimeError("Organizations require users; seed users first.")

    out: list[Organization] = []
    root_ids: list = []

    # --- Phase 1: health_system roots ---
    for i in range(counts.ORG_HIERARCHY_HEALTH_SYSTEM_ROOTS):
        oid = _stable_id(i)
        row = Organization(
            id=oid,
            name=f"{practice_name(rng, i)} Health System",
            type="health_system",
            owner_id=rng.choice(users).id,
            parent_org_id=None,
            root_org_id=oid,
        )
        await session.merge(row)
        out.append(row)
        root_ids.append(oid)

    # --- Phase 2: child orgs under each root ---
    index = counts.ORG_HIERARCHY_HEALTH_SYSTEM_ROOTS
    for root_index, root_id in enumerate(root_ids):
        for child_n in range(counts.ORG_HIERARCHY_CHILDREN_PER_ROOT):
            oid = _stable_id(index)
            # Children are clinics or group practices — both natural
            # under a health system. Round-robin so both appear.
            child_type = "clinic" if child_n % 2 == 0 else "group_practice"
            row = Organization(
                id=oid,
                name=f"{practice_name(rng, index)} (Site {child_n + 1})",
                type=child_type,
                owner_id=rng.choice(users).id,
                parent_org_id=root_id,
                root_org_id=root_id,
            )
            await session.merge(row)
            out.append(row)
            index += 1

    # --- Phase 3: standalone orgs, round-robin all ORGANIZATION_TYPES ---
    while index < counts.ORGANIZATION_COUNT:
        oid = _stable_id(index)
        org_type = rng.round_robin(ORGANIZATION_TYPES, index)
        row = Organization(
            id=oid,
            name=practice_name(rng, index),
            type=org_type,
            owner_id=rng.choice(users).id,
            parent_org_id=None,
            root_org_id=oid,
        )
        await session.merge(row)
        out.append(row)
        index += 1

    await session.commit()
    return out
