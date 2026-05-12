import uuid
from typing import Any, Optional
from uuid import UUID  # Import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Need ORM models
from src.domain.models import (
    ClientReferralDetail,
    Provider,
    ProviderAvailabilityDetail,
    ProviderCertification,
    ProviderEducation,
    ProviderLicensure,
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
# per-kind Pydantic schemas in `src/schemas/posts/post.py`). Tests that
# don't care about the specifics still need a *valid* row to exercise
# route / repo / schema behavior, so these factories supply
# spec-compliant defaults and let callers override per field.

_CLIENT_REFERRAL_DEFAULTS: dict[str, Any] = {
    "location_city": "Springfield",
    "location_state": "IL",
    "location_zip": "62701",
    "location_in_person": "yes",
    "location_virtual": "no",
    "desired_times": [],
    "client_dem_ages": "adults_25_64",
    "languages": ["en"],
    "description": "needs placement",
    "services": [],
    "services_psychotherapy_modality": None,
    "insurance": "in_network",
}

_PROVIDER_AVAILABILITY_DEFAULTS: dict[str, Any] = {
    "description": None,
    "referral_instructions": None,
    "website": None,
    "practice_name": "Acme Health",
    "available_providers": "Dr. Doe; Dr. Roe",
    "location_city": "Springfield",
    "location_state": "IL",
    "location_zip": "62701",
    "in_person_sessions": "yes",
    "virtual_sessions": "no",
    "desired_times": [],
    # PA requires min-1 service on the wire — pick a stable default that
    # tests overriding `services` can assume isn't already in the list.
    "services": ["evaluation"],
    # PA requires min-1 setting on the wire — pick a stable default that
    # tests overriding `settings` can assume isn't already in the list.
    "settings": ["outpatient"],
    "treatment_modality": None,
    "client_focus": "general adult outpatient",
    "age_group": "adults_25_64",
    "languages": ["en"],
    "payment_situation": "in_network",
    "sliding_scale": False,
    "cost": None,
}


def client_referral_payload(**overrides: Any) -> dict[str, Any]:
    """Build a wire-valid `kind='client_referral'` create/update payload.
    Returns a fresh dict each call. Pass overrides by field name to
    customize."""
    return {"kind": "client_referral", **_CLIENT_REFERRAL_DEFAULTS, **overrides}


def provider_availability_payload(**overrides: Any) -> dict[str, Any]:
    """Build a wire-valid `kind='provider_availability'` create/update payload.
    Returns a fresh dict each call."""
    return {
        "kind": "provider_availability",
        **_PROVIDER_AVAILABILITY_DEFAULTS,
        **overrides,
    }


def make_client_referral_detail(**overrides: Any) -> ClientReferralDetail:
    """Build a `ClientReferralDetail` ORM row with spec-compliant defaults."""
    return ClientReferralDetail(**{**_CLIENT_REFERRAL_DEFAULTS, **overrides})


def make_provider_availability_detail(**overrides: Any) -> ProviderAvailabilityDetail:
    """Build a `ProviderAvailabilityDetail` ORM row with spec-compliant defaults."""
    return ProviderAvailabilityDetail(
        **{**_PROVIDER_AVAILABILITY_DEFAULTS, **overrides}
    )


# --- Provider + credential sub-table factories ---------------------------
#
# Defaults supply CHECK-constraint-valid values so tests that don't care
# about credential specifics still produce inserts that pass DB-level
# guards. The owning FK (`owner_id` for providers, `provider_id` for
# sub-rows) is a required keyword-only parameter — making it required
# turns "I forgot the FK" into a `TypeError` at the factory call site
# instead of a `NOT NULL` violation at flush time.

_PROVIDER_DEFAULTS: dict[str, Any] = {
    "practice_name": "Acme Health",
    "location_city": "Springfield",
    "location_state": "IL",
    "location_zip": "62701",
    "in_person_sessions": "yes",
    "virtual_sessions": "no",
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
    omitted — credentials are added via the dedicated sub-resource endpoints."""
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
    """Build a `Provider` ORM row with CHECK-valid defaults."""
    return Provider(owner_id=owner_id, **{**_PROVIDER_DEFAULTS, **overrides})


def make_provider_licensure(
    *, provider_id: UUID, **overrides: Any
) -> ProviderLicensure:
    """Build a `ProviderLicensure` ORM row with CHECK-valid defaults."""
    return ProviderLicensure(
        provider_id=provider_id, **{**_PROVIDER_LICENSURE_DEFAULTS, **overrides}
    )


def make_provider_education(
    *, provider_id: UUID, **overrides: Any
) -> ProviderEducation:
    """Build a `ProviderEducation` ORM row with CHECK-valid defaults."""
    return ProviderEducation(
        provider_id=provider_id, **{**_PROVIDER_EDUCATION_DEFAULTS, **overrides}
    )


def make_provider_certification(
    *, provider_id: UUID, **overrides: Any
) -> ProviderCertification:
    """Build a `ProviderCertification` ORM row with CHECK-valid defaults."""
    return ProviderCertification(
        provider_id=provider_id, **{**_PROVIDER_CERTIFICATION_DEFAULTS, **overrides}
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
