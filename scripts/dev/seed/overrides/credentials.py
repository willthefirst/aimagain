"""Clinician credentials override — fan-out N per clinician.

The generic generator would create exactly `COUNT` rows; for
credentials we want a per-clinician fan-out instead (1-3 licensures,
1-2 educations, 0-3 certifications). Total row count is derived; per-
clinician counts come from `counts.py` ranges.

Coverage rules:
  - Across all rows, every LICENSE_TYPES / EDUCATION_TYPES /
    CERTIFICATION_TYPES value appears at least once (round-robin by
    the per-credential index — outer loop is clinicians, inner is
    fan-out count).
  - `issuing_state` round-robins US_STATES across licensures.
  - `expiration_date` is nullable 30%, else +1 to +5 years from today.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import (
    Clinician,
    ClinicianCertification,
    ClinicianEducation,
    ClinicianLicensure,
)
from src.domain.models.enums import (
    CERTIFICATION_TYPES,
    EDUCATION_TYPES,
    LICENSE_STATUSES,
    LICENSE_TYPES,
    US_STATES,
)

from .. import counts
from ..generators import SeedPool
from ..rng import SeededRandom, deterministic_uuid
from ..vocab import CERTIFYING_BODIES, COLUMN_VOCAB, INSTITUTIONS
from . import register


@register(ClinicianLicensure)
async def generate_licensures(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[ClinicianLicensure]:
    clinicians: list[Clinician] = pool.all("clinicians")
    lo, hi = counts.LICENSURES_PER_CLINICIAN_RANGE
    out: list[ClinicianLicensure] = []
    flat_index = 0
    for c_index, clinician in enumerate(clinicians):
        n = rng.int(lo, hi)
        for k in range(n):
            # Round-robin `status` so every CHECK-vocabulary value is
            # represented. `attested_at` is populated whenever the row
            # has been attested (any of `active`/`pending` could have
            # been the result of a positive attestation; `expired` is
            # the natural pre-attestation state).
            status = rng.round_robin(LICENSE_STATUSES, flat_index)
            attested = status == "active"
            row = ClinicianLicensure(
                id=deterministic_uuid("ClinicianLicensure", c_index, k),
                clinician_id=clinician.id,
                license_type=rng.round_robin(LICENSE_TYPES, flat_index),
                license_number=COLUMN_VOCAB["license_number"](rng, flat_index),
                issuing_state=rng.round_robin(US_STATES, flat_index),
                expiration_date=(
                    None
                    if rng.bool(0.3)
                    else rng.date_within_years(years_back=0, years_forward=5)
                ),
                status=status,
                attested_active=attested,
                attested_at=(
                    rng.date_within_years(years_back=1, years_forward=0)
                    if attested
                    else None
                ),
            )
            await session.merge(row)
            out.append(row)
            flat_index += 1
    await session.commit()
    return out


@register(ClinicianEducation)
async def generate_educations(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[ClinicianEducation]:
    clinicians: list[Clinician] = pool.all("clinicians")
    lo, hi = counts.EDUCATIONS_PER_CLINICIAN_RANGE
    out: list[ClinicianEducation] = []
    flat_index = 0
    for c_index, clinician in enumerate(clinicians):
        n = rng.int(lo, hi)
        for k in range(n):
            row = ClinicianEducation(
                id=deterministic_uuid("ClinicianEducation", c_index, k),
                clinician_id=clinician.id,
                education_type=rng.round_robin(EDUCATION_TYPES, flat_index),
                institution=rng.round_robin(INSTITUTIONS, flat_index),
                # `month_completed` is nullable — exercise the NULL path
                # so empty-state UI for the credential card is covered.
                month_completed=(
                    None
                    if rng.bool(0.2)
                    else COLUMN_VOCAB["month_completed"](rng, flat_index)
                ),
            )
            await session.merge(row)
            out.append(row)
            flat_index += 1
    await session.commit()
    return out


@register(ClinicianCertification)
async def generate_certifications(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[ClinicianCertification]:
    clinicians: list[Clinician] = pool.all("clinicians")
    lo, hi = counts.CERTIFICATIONS_PER_CLINICIAN_RANGE
    out: list[ClinicianCertification] = []
    flat_index = 0
    for c_index, clinician in enumerate(clinicians):
        n = rng.int(lo, hi)
        for k in range(n):
            row = ClinicianCertification(
                id=deterministic_uuid("ClinicianCertification", c_index, k),
                clinician_id=clinician.id,
                certification_type=rng.round_robin(CERTIFICATION_TYPES, flat_index),
                certifying_body=rng.round_robin(CERTIFYING_BODIES, flat_index),
                expiration_date=(
                    None
                    if rng.bool(0.3)
                    else rng.date_within_years(years_back=0, years_forward=5)
                ),
            )
            await session.merge(row)
            out.append(row)
            flat_index += 1
    await session.commit()
    return out
