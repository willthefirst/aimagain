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
    (in-person only), (virtual only), (both), (neither).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import Clinician, ClinicianAffiliation, Organization, User
from src.domain.models.enums import (
    CLIENT_AGE_GROUPS,
    GENDERS,
    INSURANCE_CARRIERS,
    LANGUAGES,
    LOCATION_AVAILABILITY_OPTIONS,
    NPI_MATCH_STATUSES,
    OPENING_SERVICES,
    TREATMENT_MODALITIES,
    TREATMENT_SETTINGS,
    US_STATES,
)
from src.domain.routes.dev_personas import PERSONAS

from .. import counts
from ..generators import SeedPool
from ..rng import SeededRandom, deterministic_uuid
from ..vocab import COLUMN_VOCAB, _zip_for_state
from . import register


@register(Clinician)
async def generate_clinicians(
    rng: SeededRandom, pool: SeedPool, session: AsyncSession
) -> list[Clinician]:
    all_users: list[User] = pool.all("users")
    # Persona users are excluded from the round-robin owner pool so the
    # only Clinician they own is the persona anchor created below — that
    # way the capability predicates (`any(...)` over the owned set) read
    # the persona's intended verification state instead of whatever the
    # index-driven rotation happened to assign.
    persona_emails = {p.email for p in PERSONAS}
    users: list[User] = [u for u in all_users if u.email not in persona_emails]
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
        # `languages` is the new person-level home for the field that
        # used to live on `OpeningDetail` (#1358 PR-f sub-1). Index-
        # driven round-robin (no rng draw, see same pattern in
        # `_affiliation_kwargs` below) so the shared seed RNG sequence
        # is unperturbed — that sequence drives downstream coverage
        # tests. Half the rows get a single language, half get two —
        # both monolingual and multilingual read paths exercised.
        languages = (
            [LANGUAGES[i % len(LANGUAGES)], LANGUAGES[(i + 1) % len(LANGUAGES)]]
            if i % 2 == 0
            else [LANGUAGES[i % len(LANGUAGES)]]
        )
        row = Clinician(
            id=cid,
            owner_id=users[i % len(users)].id,
            # npi is still nullable (not yet required at schema level).
            npi=(None if rng.bool(0.4) else COLUMN_VOCAB["npi"](rng, i)),
            first_name=COLUMN_VOCAB["first_name"](rng, i),
            last_name=COLUMN_VOCAB["last_name"](rng, i),
            languages=languages,
            npi_match_status=match_status,
            npi_verified_at=verified_ts,
            clinician_verified=clinician_verified,
            verified_at=verified_ts,
            ever_verified_at=verified_ts,
        )
        await session.merge(row)
        out.append(row)

    # Persona overrides — anchor a Clinician row for each persona that
    # declares one (`clinician_verified is not None`). Persona users
    # are excluded from the generic round-robin above, so this anchor
    # is the only Clinician they own. Persona registry lives in
    # `src/domain/routes/dev_personas.py`.
    persona_users_by_email = {u.email: u for u in all_users}
    for persona in PERSONAS:
        if persona.clinician_verified is None:
            continue
        user = persona_users_by_email.get(persona.email)
        if user is None:
            continue
        verified_ts = (
            rng.date_within_years(years_back=1, years_forward=0)
            if persona.clinician_verified
            else None
        )
        row = Clinician(
            id=deterministic_uuid("PersonaClinician", persona.username),
            owner_id=user.id,
            npi=None,
            first_name=persona.username.replace("-", " ").title(),
            last_name="Persona",
            languages=["en"],
            npi_match_status="matched" if persona.clinician_verified else "none",
            npi_verified_at=verified_ts,
            clinician_verified=persona.clinician_verified,
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
        # `in_person_sessions` / `virtual_sessions` are nullable: a stub
        # affiliation created at NPI verify time hasn't been asked yet.
        # ~20% NULL each so the nullable-coverage test (and any consumer
        # that reads through `clinician.in_person_sessions`) hits both
        # branches.
        "in_person_sessions": None if rng.bool(0.2) else in_person,
        "virtual_sessions": None if rng.bool(0.2) else virtual,
        "accepts_out_of_network": rng.bool(0.5),
        "in_network_carriers": rng.nullable_subset(
            INSURANCE_CARRIERS, min_size=0, max_size=6, p_empty=0.25
        ),
        "sliding_scale": rng.bool(0.3),
        "cost": (None if rng.bool(0.6) else COLUMN_VOCAB["cost"](rng, index)),
        # ---- Steady-state profile (added #1358 PR-f sub-1) ----
        # These columns are the new per-affiliation home for fields
        # that used to live on `OpeningDetail`. Use **index-driven
        # round-robin** rather than `rng.*` calls so adding these
        # fields does not perturb the shared seed RNG sequence —
        # that sequence drives downstream coverage tests (notably
        # `clinician_affiliations.location_state` round-robin via
        # `test_enum_coverage_for_every_check_constraint`). Index-
        # driven also makes the seeded shape stable as new fields
        # are added later in the chain.
        "services": [OPENING_SERVICES[index % len(OPENING_SERVICES)]],
        "settings": (
            []
            if index % 5 == 0
            else [TREATMENT_SETTINGS[index % len(TREATMENT_SETTINGS)]]
        ),
        "modalities": (
            []
            if index % 6 == 0
            else [TREATMENT_MODALITIES[index % len(TREATMENT_MODALITIES)]]
        ),
        "age_groups": [CLIENT_AGE_GROUPS[index % len(CLIENT_AGE_GROUPS)]],
        "genders": ([] if index % 5 == 0 else [GENDERS[index % len(GENDERS)]]),
        "website": (
            None if index % 3 == 0 else f"https://example.com/clinician/{index}"
        ),
        "referral_instructions": (
            None
            if index % 4 == 0
            else COLUMN_VOCAB["referral_instructions"](rng, index)
        ),
        # `currently_accepting_new_patients` defaults to False on the
        # column; lifecycle code (sub-PR 2/3) flips it. Seeding a mix
        # exercises the directory filter today.
        "currently_accepting_new_patients": index % 2 == 0,
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
        # ~20% of affiliations have null location — exercises the deferred
        # "complete your profile" path where location is filled in later.
        if rng.bool(0.2):
            kwargs["location_city"] = None
            kwargs["location_state"] = None
            kwargs["location_zip"] = None
        else:
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
