import uuid
from typing import Any, Optional
from uuid import UUID  # Import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Need ORM models
from src.domain.models import (
    IntakeDetail,
    OpeningDetail,
    Organization,
    Program,
    Provider,
    ProviderCertification,
    ProviderEducation,
    ProviderLicensure,
    ReferralDetail,
    User,
)


def create_test_user(
    id: Optional[UUID] = None,
    username: Optional[str] = None,
    email: Optional[str] = None,
    hashed_password: Optional[str] = None,
    is_active: bool = True,  # Added fastapi-users default
    is_superuser: bool = False,  # Added fastapi-users default
    is_verified: bool = True,  # Added fastapi-users default
) -> User:
    """Creates a User instance with default values for testing."""
    unique_suffix = uuid.uuid4()
    return User(
        id=id or unique_suffix,
        username=username or f"testuser_{unique_suffix}",
        email=email or f"test_{unique_suffix}@example.com",
        hashed_password=hashed_password or f"password_{unique_suffix}",
        is_active=is_active,
        is_superuser=is_superuser,
        is_verified=is_verified,
    )


# --- Per-kind detail factories --------------------------------------------
#
# Both per-kind detail tables now have many required columns (see the
# per-kind Pydantic schemas in `src/domain/logic/posts/schema.py`).
# Tests that don't care about the specifics still need a *valid* row to
# exercise route / repo / schema behavior, so these factories supply
# spec-compliant defaults and let callers override per field.

_REFERRAL_DEFAULTS: dict[str, Any] = {
    "location_city": "Springfield",
    "location_state": "IL",
    "location_zip": "62701",
    "location_in_person": "yes",
    "location_virtual": "no",
    "desired_times": [],
    "age_groups": ["adults_25_64"],
    "languages": ["en"],
    "gender": "prefer_not_to_say",
    "description": "needs placement",
    "services": [],
    "treatment_modality": None,
    "network_preference": "in_network_required",
    "insurance_carrier": None,
}

_OPENING_DEFAULTS: dict[str, Any] = {
    "description": None,
    "referral_instructions": None,
    "website": None,
    "desired_times": [],
    "schedule_text": None,
    # PA requires min-1 service on the wire — pick a stable default that
    # tests overriding `services` can assume isn't already in the list.
    "services": ["evaluation"],
    # PA requires min-1 setting on the wire — pick a stable default that
    # tests overriding `settings` can assume isn't already in the list.
    "settings": ["outpatient"],
    "treatment_modality": None,
    "age_groups": ["adults_25_64"],
    "languages": ["en"],
    # Empty allowed = "no restriction stated". Tests that exercise
    # gender semantics override; everything else gets a clean default.
    "genders": [],
}


def referral_payload(**overrides: Any) -> dict[str, Any]:
    """Build a wire-valid `kind='referral'` create/update payload.
    Returns a fresh dict each call. Pass overrides by field name to
    customize."""
    return {"kind": "referral", **_REFERRAL_DEFAULTS, **overrides}


# Stub provider_id for schema-validation tests that never hit the DB.
# Real round-trip tests pass an actual Provider's id via the kwarg.
_STUB_PROVIDER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def opening_payload(**overrides: Any) -> dict[str, Any]:
    """Build a wire-valid `kind='clinician_opening'` create/update payload.
    Returns a fresh dict each call. `provider_id` defaults to a stub UUID
    that passes Pydantic validation but does *not* exist in the DB —
    tests that actually persist must pass a real provider_id override."""
    return {
        "kind": "clinician_opening",
        "provider_id": str(_STUB_PROVIDER_ID),
        **_OPENING_DEFAULTS,
        **overrides,
    }


def make_referral_detail(**overrides: Any) -> ReferralDetail:
    """Build a `ReferralDetail` ORM row with spec-compliant defaults."""
    return ReferralDetail(**{**_REFERRAL_DEFAULTS, **overrides})


# Program-availability mirrors PA's shape: an FK to the target row plus the
# same per-announcement field set. Pydantic-side and ORM-side factories
# below use the same defaults to keep round-trip tests aligned.

_PROGRAM_AVAILABILITY_DEFAULTS: dict[str, Any] = {
    "description": None,
    "referral_instructions": None,
    "website": None,
    "desired_times": [],
    "schedule_text": None,
    "services": ["evaluation"],
    "settings": ["outpatient"],
    "treatment_modality": None,
    "age_groups": ["adults_25_64"],
    "languages": ["en"],
    "genders": [],
}

# Stub program_id for schema-validation tests that never hit the DB.
# Real round-trip tests pass an actual Program's id via the kwarg.
_STUB_PROGRAM_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def intake_payload(**overrides: Any) -> dict[str, Any]:
    """Build a wire-valid `kind='program_intake'` create/update payload.
    Returns a fresh dict each call. `program_id` defaults to a stub UUID
    that passes Pydantic validation but does *not* exist in the DB —
    tests that actually persist must pass a real program_id override."""
    return {
        "kind": "program_intake",
        "program_id": str(_STUB_PROGRAM_ID),
        **_PROGRAM_AVAILABILITY_DEFAULTS,
        **overrides,
    }


def make_intake_detail(*, program_id: UUID, **overrides: Any) -> IntakeDetail:
    """Build a `IntakeDetail` ORM row with spec-compliant
    defaults. `program_id` is a required kwarg — making it required
    turns "I forgot the FK" into a `TypeError` at the factory call site
    instead of a `NOT NULL` violation at flush time (mirrors
    :func:`make_opening_detail`)."""
    return IntakeDetail(
        program_id=program_id, **{**_PROGRAM_AVAILABILITY_DEFAULTS, **overrides}
    )


def make_program(
    *, owner_id: UUID, org_id: UUID, name: str = "RISE IOP", **overrides: Any
) -> Program:
    """Build a `Program` ORM row. ``owner_id`` and ``org_id`` are required
    kwargs — both columns are NOT NULL on the model."""
    return Program(owner_id=owner_id, org_id=org_id, name=name, **overrides)


def make_opening_detail(*, provider_id: UUID, **overrides: Any) -> OpeningDetail:
    """Build a `OpeningDetail` ORM row with spec-compliant
    defaults. `provider_id` is a required kwarg — PA points at a Provider,
    and forgetting the FK should be a `TypeError` at construction rather
    than a NOT NULL violation at flush."""
    return OpeningDetail(provider_id=provider_id, **{**_OPENING_DEFAULTS, **overrides})


# --- Provider + credential sub-table factories ---------------------------
#
# Defaults supply CHECK-constraint-valid values so tests that don't care
# about credential specifics still produce inserts that pass DB-level
# guards. The owning FK (`owner_id` for providers, `provider_id` for
# sub-rows) is a required keyword-only parameter — making it required
# turns "I forgot the FK" into a `TypeError` at the factory call site
# instead of a `NOT NULL` violation at flush time.

_PROVIDER_DEFAULTS: dict[str, Any] = {
    "location_city": "Springfield",
    "location_state": "IL",
    "location_zip": "62701",
    "in_person_sessions": "yes",
    "virtual_sessions": "no",
    # Insurance posture: empty carrier list (no in-network) + OON on by
    # default (matches the model's `server_default`). Tests that need a
    # pure self-pay shape pass `accepts_out_of_network=False` explicitly.
    "accepts_out_of_network": True,
    "in_network_carriers": [],
    "sliding_scale": False,
    "cost": None,
}

_PROVIDER_LICENSURE_DEFAULTS: dict[str, Any] = {
    "license_type": "lcsw",
    "license_number": "L-12345",
    "issuing_state": "IL",
    "expiration_date": None,
}

_PROVIDER_EDUCATION_DEFAULTS: dict[str, Any] = {
    "education_type": "msw",
    "institution": "State University",
    "month_completed": None,
}

_PROVIDER_CERTIFICATION_DEFAULTS: dict[str, Any] = {
    "certification_type": "emdr",
    "certifying_body": "EMDRIA",
    "expiration_date": None,
}


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is `None`. Form-encoded HTTP requests collapse
    `None` to an empty string on the wire, which then 422s any Pydantic
    `T | None` field that can't coerce '' (e.g. `date | None`). The form
    contract is "absent field = leave as default", so dropping `None` keys
    here matches that contract before httpx serializes the dict."""
    return {k: v for k, v in d.items() if v is not None}


def provider_payload(**overrides: Any) -> dict[str, Any]:
    """Build a wire-valid `POST /providers` form-encoded payload.
    Returns a fresh flat dict each call. Sub-entity arrays are intentionally
    omitted — credentials are added via the dedicated sub-resource endpoints.

    ``org_id`` is required on the wire. Callers that hit a real DB must
    pass an existing Organization's id; pure schema-validation tests that
    don't persist can pass any UUID."""
    return _drop_none({**_PROVIDER_DEFAULTS, **overrides})


def licensure_payload(**overrides: Any) -> dict[str, Any]:
    """Build a wire-valid `POST /providers/{id}/licensures` payload."""
    return _drop_none({**_PROVIDER_LICENSURE_DEFAULTS, **overrides})


def education_payload(**overrides: Any) -> dict[str, Any]:
    """Build a wire-valid `POST /providers/{id}/educations` payload."""
    return _drop_none({**_PROVIDER_EDUCATION_DEFAULTS, **overrides})


def certification_payload(**overrides: Any) -> dict[str, Any]:
    """Build a wire-valid `POST /providers/{id}/certifications` payload."""
    return _drop_none({**_PROVIDER_CERTIFICATION_DEFAULTS, **overrides})


def make_provider(*, owner_id: UUID, **overrides: Any) -> Provider:
    """Build a `Provider` ORM row with CHECK-valid defaults.

    ``Provider.org_id`` is NOT NULL (#524 — the former ``practice_name``
    mirror was dropped). Callers persisting the returned row must pass
    ``org_id=<existing-org.id>`` in ``overrides`` (Org persisted
    separately via ``make_organization_row`` + ``session.add``), or use
    :func:`make_provider_with_org` which builds the Org + Provider in
    one call. Bare ORM constructors without an ``org_id`` will trip the
    NOT NULL constraint at flush time.
    """
    return Provider(owner_id=owner_id, **{**_PROVIDER_DEFAULTS, **overrides})


def make_organization_row(
    *,
    owner_id: UUID,
    name: str = "Acme Health",
    type_: str = "solo_practice",
    org_id: UUID | None = None,
) -> Organization:
    """Build a root ``Organization`` ORM row that satisfies the
    ``root_org_id`` invariant (root: ``root_org_id = id``,
    ``parent_org_id = NULL``).

    Assigns ``id`` eagerly so callers can pass ``org.id`` straight into
    a sibling ``make_provider`` without an intermediate flush — mirrors
    the eager assignment ``OrganizationRepository.create`` does."""
    obj = Organization(
        id=org_id or uuid.uuid4(),
        name=name,
        type=type_,
        owner_id=owner_id,
    )
    obj.root_org_id = obj.id
    return obj


def make_provider_with_org(
    *,
    owner_id: UUID,
    practice_name: str = "Acme Health",
    org: Organization | None = None,
    **overrides: Any,
) -> Provider:
    """Build a Provider wired to an Organization. ``Organization.name``
    is the practice's display name; tests that previously asserted on
    ``provider.practice_name`` now read ``provider.org.name``.

    The Org is attached via ``provider.org = org`` rather than just
    ``org_id`` so SQLAlchemy's default save-update cascade picks the
    Org up when the Provider is added to a session — callers stay on
    the single-add ``session.add(provider)`` shape.

    ``practice_name`` here names the *Organization* — the kwarg is
    kept under that name for call-site stability. Pass ``org=<instance>``
    when multiple Providers share an Org; the kwarg is ignored in that
    case (the existing Org's name wins)."""
    if org is None:
        org = make_organization_row(owner_id=owner_id, name=practice_name)
    provider = make_provider(
        owner_id=owner_id,
        org_id=org.id,
        **{k: v for k, v in overrides.items() if k != "practice_name"},
    )
    provider.org = org
    return provider


def make_provider_licensure(
    *,
    clinician_id: UUID,
    **overrides: Any,
) -> ProviderLicensure:
    """Build a `ProviderLicensure` ORM row with CHECK-valid defaults.
    Credentials FK to `clinicians.id` after #635 PR A — pass
    `clinician_id=provider.clinician_id` after the provider has been
    flushed (or `provider.clinician.id` if the clinician is flushed)."""
    return ProviderLicensure(
        clinician_id=clinician_id,
        **{**_PROVIDER_LICENSURE_DEFAULTS, **overrides},
    )


def make_provider_education(
    *,
    clinician_id: UUID,
    **overrides: Any,
) -> ProviderEducation:
    """Build a `ProviderEducation` ORM row. See
    :func:`make_provider_licensure` for the FK contract."""
    return ProviderEducation(
        clinician_id=clinician_id,
        **{**_PROVIDER_EDUCATION_DEFAULTS, **overrides},
    )


def make_provider_certification(
    *,
    clinician_id: UUID,
    **overrides: Any,
) -> ProviderCertification:
    """Build a `ProviderCertification` ORM row. See
    :func:`make_provider_licensure` for the FK contract."""
    return ProviderCertification(
        clinician_id=clinician_id,
        **{**_PROVIDER_CERTIFICATION_DEFAULTS, **overrides},
    )


async def promote_to_admin(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    user_email: str,
) -> None:
    """Mutate a fixture-created user to is_superuser=True.

    Used by colocated tests that need an admin actor — the standard
    `authenticated_client` fixture creates a non-admin user, so tests that
    exercise admin-gated routes flip the bit on the existing user instead of
    reauthenticating as a different one.
    """
    async with db_test_session_manager() as session:
        async with session.begin():
            stmt = select(User).filter(User.email == user_email)
            result = await session.execute(stmt)
            user = result.scalars().first()
            assert user is not None, f"Test user {user_email} not found"
            user.is_superuser = True
