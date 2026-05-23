"""Clinician + Provider + Affiliation overrides.

The three models are tightly coupled by `Provider.__init__`'s
auto-create path: passing per-role kwargs to `Provider(...)` would
build a transient Clinician and Affiliation. The seed bypasses that
by passing `clinician=...` and `affiliations=[...]` explicitly so
every row has a deterministic stable PK (needed for idempotency).

Cardinality:
  - one Clinician per Provider for the first PROVIDER_COUNT slots.
  - PROVIDER_COUNT Providers, each FK'd to its same-indexed clinician.
  - PROVIDER_COUNT base Affiliations + ~25% second Affiliations at a
    different org — exercises multi-affiliation read paths.

Coverage:
  - `location_state` round-robins all 51 US_STATES so every state
    appears at least once (PROVIDER_COUNT > 51).
  - `in_person_sessions` and `virtual_sessions` independently
    round-robin LOCATION_AVAILABILITY_OPTIONS — produces rows for
    (in-person only), (virtual only), (both), (please_contact).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import Affiliation, Clinician, Organization, Provider, User
from src.domain.models.enums import (
    INSURANCE_CARRIERS,
    LOCATION_AVAILABILITY_OPTIONS,
    US_STATES,
)

from .. import counts
from ..generators import SeedPool
from ..rng import SeededRandom, deterministic_uuid
from ..vocab import COLUMN_VOCAB, _zip_for_state
from . import register


@register(Clinician)
async def generate_clinicians(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[Clinician]:
    """One Clinician per planned Provider; Provider FK's the same index."""
    out: list[Clinician] = []
    for i in range(counts.PROVIDER_COUNT):
        cid = deterministic_uuid("Clinician", i)
        row = Clinician(
            id=cid,
            # All three are nullable per the model. Exercise the NULL
            # path so the nullable-coverage test has both samples.
            npi=(None if rng.bool(0.4) else COLUMN_VOCAB["npi"](rng, i)),
            first_name=(None if rng.bool(0.1) else COLUMN_VOCAB["first_name"](rng, i)),
            last_name=(None if rng.bool(0.1) else COLUMN_VOCAB["last_name"](rng, i)),
        )
        await session.merge(row)
        out.append(row)
    await session.commit()
    return out


def _affiliation_kwargs(rng: SeededRandom, index: int) -> dict:
    """Per-affiliation column values. Round-robin every CHECK-bound
    column so the dataset hits every allowed combination at least once
    across the COUNT axis."""
    state = rng.round_robin(US_STATES, index)
    in_person = rng.round_robin(LOCATION_AVAILABILITY_OPTIONS, index)
    virtual = rng.round_robin(LOCATION_AVAILABILITY_OPTIONS, index + 1)
    return {
        "location_state": state,
        "location_city": (
            "Springfield"
            if state not in {"CA", "TX", "NY", "FL", "IL", "PA", "OH"}
            else state
        ),  # placeholder; the runner override below uses CITIES_BY_STATE
        "location_zip": _zip_for_state(rng, state),
        "in_person_sessions": in_person,
        "virtual_sessions": virtual,
        "accepts_out_of_network": rng.bool(0.5),
        "in_network_carriers": rng.nullable_subset(
            INSURANCE_CARRIERS, min_size=0, max_size=6, p_empty=0.25
        ),
        "sliding_scale": rng.bool(0.3),
        "cost": (None if rng.bool(0.6) else COLUMN_VOCAB["cost"](rng, index)),
    }


def _city_for_state(rng: SeededRandom, state: str) -> str:
    from ..vocab import CITIES_BY_STATE

    cities = CITIES_BY_STATE.get(state)
    if not cities:
        return "Springfield"
    return rng.choice(cities)


@register(Provider)
async def generate_providers(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[Provider]:
    users: list[User] = pool.all("users")
    clinicians: list[Clinician] = pool.all("clinicians")

    out: list[Provider] = []
    for i in range(counts.PROVIDER_COUNT):
        pid = deterministic_uuid("Provider", i)
        clinician = clinicians[i % len(clinicians)]
        # Pass `clinician=` and `affiliations=[]` to suppress the
        # Provider.__init__ auto-create path; we want stable PKs.
        provider = Provider(
            id=pid,
            owner_id=users[i % len(users)].id,
            clinician=clinician,
            affiliations=[],
        )
        # No `merge` here: Provider with affiliations=[] passed
        # explicitly is fine to insert (Provider.id has a deterministic
        # PK so rerun matches). `merge` does insert-or-update keyed on
        # PK.
        merged = await session.merge(provider)
        out.append(merged)
    await session.commit()
    return out


@register(Affiliation)
async def generate_affiliations(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[Affiliation]:
    providers: list[Provider] = pool.all("providers")
    orgs: list[Organization] = pool.all("organizations")
    clinicians: list[Clinician] = pool.all("clinicians")

    out: list[Affiliation] = []
    aff_index = 0
    for i, provider in enumerate(providers):
        # Primary affiliation — deterministic ID keyed (provider, 0).
        primary_id = deterministic_uuid("Affiliation", i, 0)
        kwargs = _affiliation_kwargs(rng, aff_index)
        kwargs["location_city"] = _city_for_state(rng, kwargs["location_state"])
        primary = Affiliation(
            id=primary_id,
            provider_id=provider.id,
            clinician_id=clinicians[i % len(clinicians)].id,
            org_id=orgs[i % len(orgs)].id,
            **kwargs,
        )
        await session.merge(primary)
        out.append(primary)
        aff_index += 1

        # ~25% of providers get a second affiliation at a different org.
        if rng.bool(counts.PROVIDER_MULTI_AFFILIATION_RATE):
            secondary_id = deterministic_uuid("Affiliation", i, 1)
            other_org = orgs[(i + 7) % len(orgs)]  # +7 to avoid same-org
            kwargs2 = _affiliation_kwargs(rng, aff_index)
            kwargs2["location_city"] = _city_for_state(rng, kwargs2["location_state"])
            secondary = Affiliation(
                id=secondary_id,
                provider_id=provider.id,
                clinician_id=clinicians[i % len(clinicians)].id,
                org_id=other_org.id,
                **kwargs2,
            )
            await session.merge(secondary)
            out.append(secondary)
            aff_index += 1
    await session.commit()
    return out
