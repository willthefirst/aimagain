"""Clinician + ClinicianAffiliation overrides.

Cardinality:
  - CLINICIAN_COUNT Clinicians, each with `owner_id` assigned from the
    users pool (round-robin) and `npi`/`first_name`/`last_name` from vocab.
  - CLINICIAN_COUNT base Affiliations + ~25% second Affiliations at a
    different org — exercises multi-affiliation read paths.

Coverage:
  - `location_state` round-robins all 51 US_STATES so every state
    appears at least once (CLINICIAN_COUNT > 51).
  - `in_person_sessions` and `virtual_sessions` independently
    round-robin LOCATION_AVAILABILITY_OPTIONS — produces rows for
    (in-person only), (virtual only), (both), (please_contact).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import Clinician, ClinicianAffiliation, Organization, User
from src.domain.models.enums import (
    INSURANCE_CARRIERS,
    LOCATION_AVAILABILITY_OPTIONS,
    NPI_MATCH_STATUSES,
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
    users: list[User] = pool.all("users")
    out: list[Clinician] = []
    for i in range(counts.CLINICIAN_COUNT):
        cid = deterministic_uuid("Clinician", i)
        # Round-robin `NPI_MATCH_STATUSES` so every CHECK-vocabulary
        # value appears in the dataset. Whichever bucket the row falls
        # into drives whether `clinician_verified` and the
        # `*_verified_at` timestamps get filled (a `matched` row is the
        # post-NPPES happy path; `none` is pre-submit).
        match_status = rng.round_robin(NPI_MATCH_STATUSES, i)
        clinician_verified = match_status == "matched"
        verified_ts = (
            rng.date_within_years(years_back=1, years_forward=0)
            if clinician_verified
            else None
        )
        row = Clinician(
            id=cid,
            owner_id=users[i % len(users)].id,
            # All three are nullable per the model. Exercise the NULL
            # path so the nullable-coverage test has both samples.
            npi=(None if rng.bool(0.4) else COLUMN_VOCAB["npi"](rng, i)),
            first_name=(None if rng.bool(0.1) else COLUMN_VOCAB["first_name"](rng, i)),
            last_name=(None if rng.bool(0.1) else COLUMN_VOCAB["last_name"](rng, i)),
            npi_match_status=match_status,
            npi_verified_at=verified_ts,
            clinician_verified=clinician_verified,
            verified_at=verified_ts,
            ever_verified_at=verified_ts,
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


@register(ClinicianAffiliation)
async def generate_affiliations(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[ClinicianAffiliation]:
    clinicians: list[Clinician] = pool.all("clinicians")
    orgs: list[Organization] = pool.all("organizations")

    out: list[ClinicianAffiliation] = []
    aff_index = 0
    for i, clinician in enumerate(clinicians):
        # Primary affiliation — deterministic ID keyed (clinician, 0).
        primary_id = deterministic_uuid("ClinicianAffiliation", i, 0)
        kwargs = _affiliation_kwargs(rng, aff_index)
        kwargs["location_city"] = _city_for_state(rng, kwargs["location_state"])
        primary = ClinicianAffiliation(
            id=primary_id,
            clinician_id=clinician.id,
            org_id=orgs[i % len(orgs)].id,
            **kwargs,
        )
        await session.merge(primary)
        out.append(primary)
        aff_index += 1

        # ~25% of clinicians get a second affiliation at a different org.
        if rng.bool(counts.CLINICIAN_MULTI_AFFILIATION_RATE):
            secondary_id = deterministic_uuid("ClinicianAffiliation", i, 1)
            other_org = orgs[(i + 7) % len(orgs)]  # +7 to avoid same-org
            kwargs2 = _affiliation_kwargs(rng, aff_index)
            kwargs2["location_city"] = _city_for_state(rng, kwargs2["location_state"])
            secondary = ClinicianAffiliation(
                id=secondary_id,
                clinician_id=clinician.id,
                org_id=other_org.id,
                **kwargs2,
            )
            await session.merge(secondary)
            out.append(secondary)
            aff_index += 1
    await session.commit()
    return out
