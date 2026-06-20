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
from src.domain.models.enums import (
    CLIENT_AGE_GROUPS,
    GENDERS,
    LANGUAGES,
    OPENING_SERVICES,
    TREATMENT_MODALITIES,
    TREATMENT_SETTINGS,
    US_STATES,
)

from .. import counts
from ..generators import SeedPool
from ..rng import SeededRandom, deterministic_uuid
from ..vocab import COLUMN_VOCAB, INTAKE_SUBJECTS, program_name
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
        # ---- Steady-state profile (added #1358 PR-f sub-1) ----
        # Symmetric to the affiliation override; see
        # ``overrides/clinicians.py`` for the rationale. ``languages``
        # lands on the Program (not on a person) since the Program is
        # the offering. Use **index-driven round-robin** rather than
        # `rng.*` calls so adding fields here doesn't perturb the
        # downstream coverage tests.
        services = [OPENING_SERVICES[i % len(OPENING_SERVICES)]]
        settings = (
            [] if i % 5 == 0 else [TREATMENT_SETTINGS[i % len(TREATMENT_SETTINGS)]]
        )
        modalities = (
            [] if i % 6 == 0 else [TREATMENT_MODALITIES[i % len(TREATMENT_MODALITIES)]]
        )
        age_groups = [CLIENT_AGE_GROUPS[i % len(CLIENT_AGE_GROUPS)]]
        genders = [] if i % 5 == 0 else [GENDERS[i % len(GENDERS)]]
        # Two languages on every other row, one on the rest — never
        # empty (the Program is the offering; an empty languages list
        # is unusual in practice).
        languages = (
            [LANGUAGES[i % len(LANGUAGES)], LANGUAGES[(i + 1) % len(LANGUAGES)]]
            if i % 2 == 0
            else [LANGUAGES[i % len(LANGUAGES)]]
        )
        # Row 0 explicitly NULLs the new text columns to guarantee
        # NULL coverage in the small Program seed set, same
        # rationale as `description=None` above.
        if i == 0:
            website = None
            referral_instructions = None
        else:
            website = f"https://example.com/program/{i}" if i % 3 != 0 else None
            referral_instructions = (
                None if i % 4 == 0 else COLUMN_VOCAB["referral_instructions"](rng, i)
            )
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
            services=services,
            settings=settings,
            modalities=modalities,
            age_groups=age_groups,
            genders=genders,
            languages=languages,
            website=website,
            referral_instructions=referral_instructions,
            currently_accepting_new_patients=i % 2 == 0,
        )
        await session.merge(row)
        out.append(row)

    await session.commit()
    return out
