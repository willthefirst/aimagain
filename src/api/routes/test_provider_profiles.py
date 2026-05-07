import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import (
    ProviderCertification,
    ProviderEducation,
    ProviderLicensure,
    ProviderProfile,
    User,
)
from src.repositories.audit_repository import AuditRepository
from tests.helpers import (
    certification_payload,
    create_test_user,
    education_payload,
    licensure_payload,
    make_provider_certification,
    make_provider_education,
    make_provider_licensure,
    make_provider_profile,
    provider_profile_payload,
)

pytestmark = pytest.mark.asyncio


# --- Helpers -------------------------------------------------------------


async def _seed_profile_for(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    **overrides,
) -> uuid.UUID:
    """Insert a profile owned by `user_id` and return its id."""
    profile = make_provider_profile(user_id=user_id, **overrides)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(profile)
        await session.refresh(profile)
        return profile.id


async def _seed_other_user_with_profile(
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a second user + their profile. Returns (user_id, profile_id)."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    profile_id = await _seed_profile_for(db_test_session_manager, user_id=other.id)
    return other.id, profile_id


async def _audit_rows_for(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    resource_type: str,
    resource_id: uuid.UUID,
):
    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        return await repo.list_for_resource(
            resource_type=resource_type, resource_id=resource_id
        )


# --- Profile create ------------------------------------------------------


async def test_create_profile_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """POST /provider-profiles with a form-encoded body returns 201 + id and
    persists the profile and an audit row."""
    response = await authenticated_client.post(
        "/provider-profiles",
        data=provider_profile_payload(practice_name="Acme Therapy"),
    )

    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])
    assert response.headers["Location"] == f"/provider-profiles/{new_id}"
    assert response.headers["HX-Redirect"] == f"/provider-profiles/{new_id}"

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ProviderProfile).filter(ProviderProfile.id == new_id)
        )
        persisted = result.scalars().first()
        assert persisted is not None
        assert persisted.user_id == logged_in_user.id
        assert persisted.practice_name == "Acme Therapy"

    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider_profile",
        resource_id=new_id,
    )
    assert len(rows) == 1
    assert rows[0].action == "create_provider_profile"
    assert rows[0].actor_id == logged_in_user.id


async def test_create_profile_returns_400_if_already_exists(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The one-profile-per-user uniqueness rule surfaces as 400 on second POST."""
    first = await authenticated_client.post(
        "/provider-profiles", data=provider_profile_payload()
    )
    assert first.status_code == 201

    second = await authenticated_client.post(
        "/provider-profiles", data=provider_profile_payload(practice_name="Other")
    )
    assert second.status_code == 400


async def test_create_profile_rejects_unknown_field(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`extra='forbid'` on the schema rejects unknown form fields with 422."""
    response = await authenticated_client.post(
        "/provider-profiles",
        data=provider_profile_payload(user_id=str(uuid.uuid4())),
    )
    assert response.status_code == 422


# --- Profile reads -------------------------------------------------------


async def test_get_profile_returns_profile(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Mine"
    )

    response = await authenticated_client.get(f"/provider-profiles/{profile_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(profile_id)
    assert body["practice_name"] == "Mine"
    assert body["licensures"] == []


async def test_get_profile_returns_404_for_unknown_id(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get(f"/provider-profiles/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_get_my_profile_returns_my_profile(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id
    )

    response = await authenticated_client.get("/provider-profiles/me")

    assert response.status_code == 200
    assert response.json()["id"] == str(profile_id)


async def test_get_my_profile_returns_404_when_not_created(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get("/provider-profiles/me")
    assert response.status_code == 404


# --- Profile listing -----------------------------------------------------


async def test_list_profiles_is_public(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The list endpoint requires no authentication."""
    other = create_test_user(username=f"public-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    await _seed_profile_for(db_test_session_manager, user_id=other.id)

    response = await test_client.get("/provider-profiles")

    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert len(response.json()) == 1


async def test_list_profiles_filters_by_license_type(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`?license_type=` keeps only profiles holding a matching licensure."""
    user_a = create_test_user(username=f"ua-{uuid.uuid4()}")
    user_b = create_test_user(username=f"ub-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user_a)
            session.add(user_b)
    profile_a = await _seed_profile_for(db_test_session_manager, user_id=user_a.id)
    profile_b = await _seed_profile_for(db_test_session_manager, user_id=user_b.id)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                make_provider_licensure(profile_id=profile_a, license_type="psyd")
            )
            session.add(
                make_provider_licensure(profile_id=profile_b, license_type="lcsw")
            )

    response = await test_client.get("/provider-profiles?license_type=psyd")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(profile_a)


# --- Profile update ------------------------------------------------------


async def test_patch_profile_updates_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Old Name"
    )

    response = await authenticated_client.patch(
        f"/provider-profiles/{profile_id}",
        data={"practice_name": "New Name"},
    )

    assert response.status_code == 200
    assert response.json()["practice_name"] == "New Name"
    assert response.headers["HX-Redirect"] == f"/provider-profiles/{profile_id}"

    async with db_test_session_manager() as session:
        refreshed = (
            (
                await session.execute(
                    select(ProviderProfile).filter(ProviderProfile.id == profile_id)
                )
            )
            .scalars()
            .first()
        )
        assert refreshed.practice_name == "New Name"


async def test_patch_profile_returns_403_if_not_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    _, other_profile_id = await _seed_other_user_with_profile(db_test_session_manager)

    response = await authenticated_client.patch(
        f"/provider-profiles/{other_profile_id}",
        data={"practice_name": "Hijack"},
    )
    assert response.status_code == 403


# --- Profile delete ------------------------------------------------------


async def test_delete_profile_returns_204_and_cascades(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(make_provider_licensure(profile_id=profile_id))
            session.add(make_provider_education(profile_id=profile_id))
            session.add(make_provider_certification(profile_id=profile_id))

    response = await authenticated_client.delete(f"/provider-profiles/{profile_id}")
    assert response.status_code == 204

    async with db_test_session_manager() as session:
        assert (
            await session.execute(
                select(ProviderProfile).filter(ProviderProfile.id == profile_id)
            )
        ).scalars().first() is None
        # Sub-rows cascade-deleted via FK ON DELETE CASCADE + ORM cascade.
        assert (
            await session.execute(
                select(ProviderLicensure).filter(
                    ProviderLicensure.profile_id == profile_id
                )
            )
        ).scalars().first() is None
        assert (
            await session.execute(
                select(ProviderEducation).filter(
                    ProviderEducation.profile_id == profile_id
                )
            )
        ).scalars().first() is None
        assert (
            await session.execute(
                select(ProviderCertification).filter(
                    ProviderCertification.profile_id == profile_id
                )
            )
        ).scalars().first() is None


async def test_delete_profile_returns_403_if_not_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    _, other_profile_id = await _seed_other_user_with_profile(db_test_session_manager)

    response = await authenticated_client.delete(
        f"/provider-profiles/{other_profile_id}"
    )
    assert response.status_code == 403


# --- Licensure sub-resource ---------------------------------------------


async def test_create_licensure_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id
    )

    response = await authenticated_client.post(
        f"/provider-profiles/{profile_id}/licensures",
        data=licensure_payload(license_number="L-99999"),
    )

    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])
    assert response.headers["HX-Redirect"] == f"/provider-profiles/{profile_id}"

    async with db_test_session_manager() as session:
        persisted = (
            (
                await session.execute(
                    select(ProviderLicensure).filter(ProviderLicensure.id == new_id)
                )
            )
            .scalars()
            .first()
        )
        assert persisted is not None
        assert persisted.license_number == "L-99999"
        assert persisted.profile_id == profile_id


async def test_create_licensure_returns_403_if_not_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    _, other_profile_id = await _seed_other_user_with_profile(db_test_session_manager)

    response = await authenticated_client.post(
        f"/provider-profiles/{other_profile_id}/licensures",
        data=licensure_payload(),
    )
    assert response.status_code == 403


async def test_create_licensure_returns_404_for_unknown_profile(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.post(
        f"/provider-profiles/{uuid.uuid4()}/licensures",
        data=licensure_payload(),
    )
    assert response.status_code == 404


async def test_patch_licensure_updates_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    licensure = make_provider_licensure(profile_id=profile_id, license_number="L-1")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(licensure)
        await session.refresh(licensure)
        licensure_id = licensure.id

    response = await authenticated_client.patch(
        f"/provider-profiles/{profile_id}/licensures/{licensure_id}",
        data={"license_number": "L-2"},
    )

    assert response.status_code == 200
    assert response.json()["license_number"] == "L-2"


async def test_patch_licensure_returns_404_for_mismatched_profile(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A licensure_id that belongs to a different profile must 404, not silently
    update across profile boundaries."""
    my_profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    _, other_profile_id = await _seed_other_user_with_profile(db_test_session_manager)
    other_licensure = make_provider_licensure(profile_id=other_profile_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other_licensure)
        await session.refresh(other_licensure)
        other_licensure_id = other_licensure.id

    response = await authenticated_client.patch(
        f"/provider-profiles/{my_profile_id}/licensures/{other_licensure_id}",
        data={"license_number": "stolen"},
    )
    assert response.status_code == 404


async def test_delete_licensure_returns_204(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    licensure = make_provider_licensure(profile_id=profile_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(licensure)
        await session.refresh(licensure)
        licensure_id = licensure.id

    response = await authenticated_client.delete(
        f"/provider-profiles/{profile_id}/licensures/{licensure_id}"
    )
    assert response.status_code == 204

    async with db_test_session_manager() as session:
        assert (
            await session.execute(
                select(ProviderLicensure).filter(ProviderLicensure.id == licensure_id)
            )
        ).scalars().first() is None


# --- Education / certification happy paths ------------------------------


async def test_create_education_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id
    )

    response = await authenticated_client.post(
        f"/provider-profiles/{profile_id}/educations",
        data=education_payload(institution="Test U"),
    )

    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        persisted = (
            (
                await session.execute(
                    select(ProviderEducation).filter(ProviderEducation.id == new_id)
                )
            )
            .scalars()
            .first()
        )
        assert persisted is not None
        assert persisted.institution == "Test U"


async def test_create_certification_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id
    )

    response = await authenticated_client.post(
        f"/provider-profiles/{profile_id}/certifications",
        data=certification_payload(certifying_body="Test Cert Body"),
    )

    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        persisted = (
            (
                await session.execute(
                    select(ProviderCertification).filter(
                        ProviderCertification.id == new_id
                    )
                )
            )
            .scalars()
            .first()
        )
        assert persisted is not None
        assert persisted.certifying_body == "Test Cert Body"
