"""Onboarding wizard service functions.

Each function here is a "thin bespoke shim" called from a wizard POST handler.
The shim validates form data (via schema.py), delegates to existing domain
handlers / repos, and owns the transaction boundary (or delegates it to the
verification pipeline which commits at the end).

Pattern: every wizard write is a function here that:
  1. Creates / mutates rows via existing repo primitives or model constructors
  2. Calls the verification pipeline (which commits) or commits explicitly
  3. Returns the primary created/updated model

No `return_to` primitive — redirects are always determined by `next_step()`.
"""

import uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.logic.onboarding.schema import VerifyForm
from src.domain.logic.providers.repository import ProviderRepository
from src.domain.logic.verifications.handlers import run_provider_verification
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import Organization, Provider, ProviderLicensure, User
from src.framework.audit.repository import AuditRepository

_HTTP_TIMEOUT_SECONDS = 10.0


async def verify_and_create_clinician(
    form_data: VerifyForm,
    user: User,
    *,
    db: AsyncSession,
) -> Provider:
    """Create a Clinician (via Provider constructor), Licensure, and run
    NPPES/OIG verification — all in a single transaction.

    Atomicity: all row creation is flushed (not committed) until
    `run_provider_verification` commits at the end. If the pipeline raises
    before committing, none of the flushed rows persist.

    If verification yields status 'failed', the Clinician/Provider/Licensure
    rows **still exist** — the wizard lets the user see the failure and
    re-submit. Only an unhandled exception (DB error, network crash during
    NPPES before the ORM flush) rolls back and leaves no orphans.

    Returns the created Provider (always, even on verification failure).
    """
    # 1. Auto-create a solo-practice Organization for this clinician.
    #    root_org_id is NOT NULL with no server default — set it to the
    #    org's own id to make this a root org (parent_org_id IS NULL).
    #    Mirrors OrganizationRepository.create and make_organization_row.
    name_parts = [p for p in (form_data.first_name, form_data.last_name) if p.strip()]
    org_name = (
        " ".join(name_parts) if name_parts else (user.username or "Solo Practice")
    )
    org_id = uuid.uuid4()
    org = Organization(
        id=org_id,
        name=org_name,
        type="solo_practice",
        owner_id=user.id,
    )
    org.root_org_id = org_id
    db.add(org)
    await db.flush()

    # 2. Create Provider — the constructor auto-creates a Clinician (from
    # first_name/last_name) and an Affiliation (from the per-role kwargs).
    # location_city/zip are required NOT NULL on Affiliation; use empty-string
    # placeholders — the user fills real values in the profile steps (T5/T7).
    # location_state is seeded from the license issuing_state (best available
    # proxy at this point in the wizard).
    provider = Provider(
        owner_id=user.id,
        first_name=form_data.first_name,
        last_name=form_data.last_name,
        org_id=org.id,
        location_city="",
        location_state=form_data.issuing_state,
        location_zip="",
        in_person_sessions="please_contact",
        virtual_sessions="please_contact",
    )
    db.add(provider)
    await db.flush()
    await db.refresh(provider)

    # 3. Add the license that was submitted on the verify form.
    #    FK is to clinicians.id (not providers.id) — #635 PR A moved creds.
    licensure = ProviderLicensure(
        clinician_id=provider.clinician.id,
        license_type=form_data.license_type,
        license_number=form_data.license_number,
        issuing_state=form_data.issuing_state,
    )
    db.add(licensure)
    await db.flush()
    await db.refresh(licensure)

    # 4. Run the NPPES + OIG + scoring pipeline.  `run_provider_verification`
    # commits the session at the end — all flushed rows above commit with it.
    # Using `run_provider_verification` (not `handle_create_provider_verification`)
    # because the latter enforces `is_superuser`; the wizard is a self-service path.
    provider_repo = ProviderRepository(db)
    verification_repo = VerificationRepository(db)
    audit_repo = AuditRepository(db)

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as http:
        await run_provider_verification(
            provider_id=provider.id,
            verification_repo=verification_repo,
            provider_repo=provider_repo,
            audit_repo=audit_repo,
            http=http,
            actor_id=user.id,
        )

    return provider
