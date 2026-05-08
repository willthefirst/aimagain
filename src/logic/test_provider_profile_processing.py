"""Tests for provider-profile orchestration handlers.

Exercises happy-path + ownership / not-found / bad-request error cases for
each handler. Audit-row assertions verify that mutation handlers honor the
discipline (`test_audit_discipline.py` enforces it statically; these tests
verify the rows actually land with the expected `action` and snapshots).
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from src.api.common.exceptions import BadRequestError, ForbiddenError, NotFoundError
from src.logic.audit import AuditAction
from src.logic.provider_profile_processing import (
    handle_create_certification,
    handle_create_education,
    handle_create_licensure,
    handle_create_profile,
    handle_delete_certification,
    handle_delete_education,
    handle_delete_licensure,
    handle_delete_profile,
    handle_get_my_provider_profile_detail,
    handle_get_provider_profile_detail,
    handle_list_provider_profiles,
    handle_update_certification,
    handle_update_education,
    handle_update_licensure,
    handle_update_profile,
)
from src.models import (
    AuditLog,
    ProviderCertification,
    ProviderEducation,
    ProviderLicensure,
    ProviderProfile,
    User,
)
from src.repositories.audit_repository import AuditRepository
from src.repositories.provider_profile_repository import ProviderProfileRepository
from src.schemas.provider_profile import (
    ProviderCertificationCreate,
    ProviderCertificationUpdate,
    ProviderEducationCreate,
    ProviderEducationUpdate,
    ProviderLicensureCreate,
    ProviderLicensureUpdate,
    ProviderProfileCreate,
    ProviderProfileUpdate,
)
from tests.helpers import (
    create_test_user,
    make_provider_certification,
    make_provider_education,
    make_provider_licensure,
    make_provider_profile,
)

pytestmark = pytest.mark.asyncio


def _fake_request() -> Request:
    """Minimal Starlette Request used as a placeholder for handlers that
    forward the request into a template context but don't otherwise read
    from it."""
    return Request({"type": "http", "headers": [], "method": "GET", "path": "/"})


# --- Seeding helpers -----------------------------------------------------


async def _seed_user(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    is_superuser: bool = False,
) -> User:
    user = create_test_user(username=f"u-{uuid.uuid4()}", is_superuser=is_superuser)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
    return user


async def _seed_profile(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    with_licensure: bool = False,
    with_education: bool = False,
    with_certification: bool = False,
) -> tuple[uuid.UUID, uuid.UUID | None, uuid.UUID | None, uuid.UUID | None]:
    profile = make_provider_profile(user_id=user_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(profile)
        await session.refresh(profile)
        profile_id = profile.id

    licensure_id: uuid.UUID | None = None
    education_id: uuid.UUID | None = None
    certification_id: uuid.UUID | None = None
    async with db_test_session_manager() as session:
        async with session.begin():
            if with_licensure:
                lic = make_provider_licensure(profile_id=profile_id)
                session.add(lic)
            if with_education:
                edu = make_provider_education(profile_id=profile_id)
                session.add(edu)
            if with_certification:
                cert = make_provider_certification(profile_id=profile_id)
                session.add(cert)
        if with_licensure:
            await session.refresh(lic)
            licensure_id = lic.id
        if with_education:
            await session.refresh(edu)
            education_id = edu.id
        if with_certification:
            await session.refresh(cert)
            certification_id = cert.id

    return profile_id, licensure_id, education_id, certification_id


def _profile_create_payload(**overrides) -> ProviderProfileCreate:
    base = dict(
        practice_name="Acme Health",
        location_city="Springfield",
        location_state="IL",
        location_zip="62701",
        in_person_sessions="yes",
        virtual_sessions="no",
    )
    base.update(overrides)
    return ProviderProfileCreate(**base)


async def _audit_rows_for(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    resource_type: str,
    resource_id: uuid.UUID,
) -> list[AuditLog]:
    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(
            resource_type=resource_type, resource_id=resource_id
        )
        return list(rows)


# --- Profile reads -------------------------------------------------------


async def test_list_provider_profiles_returns_persisted_profiles(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user_a = await _seed_user(db_test_session_manager)
    user_b = await _seed_user(db_test_session_manager)
    await _seed_profile(db_test_session_manager, user_id=user_a.id)
    await _seed_profile(db_test_session_manager, user_id=user_b.id)

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        context = await handle_list_provider_profiles(
            request=_fake_request(), repo=repo
        )
        assert len(context["profiles"]) == 2
        assert context["selected_license_type"] is None
        assert context["selected_issuing_state"] is None


async def test_list_provider_profiles_filters_by_license_type(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user_a = await _seed_user(db_test_session_manager)
    user_b = await _seed_user(db_test_session_manager)
    profile_a, *_ = await _seed_profile(
        db_test_session_manager, user_id=user_a.id, with_licensure=True
    )
    profile_b, *_ = await _seed_profile(db_test_session_manager, user_id=user_b.id)
    # Add a non-matching licensure to profile_b
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                make_provider_licensure(profile_id=profile_b, license_type="lpc")
            )

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        context = await handle_list_provider_profiles(
            request=_fake_request(), repo=repo, license_type="lcsw"
        )
        assert [p.id for p in context["profiles"]] == [profile_a]
        assert context["selected_license_type"] == "lcsw"


async def test_get_provider_profile_detail_returns_context(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    profile_id, *_ = await _seed_profile(db_test_session_manager, user_id=user.id)

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        context = await handle_get_provider_profile_detail(
            request=_fake_request(),
            profile_id=profile_id,
            repo=repo,
            requesting_user=user,
        )
        assert context["profile"].id == profile_id
        assert context["current_user"] is user
        assert "request" in context


async def test_get_provider_profile_detail_404_for_unknown_id(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        with pytest.raises(NotFoundError):
            await handle_get_provider_profile_detail(
                request=_fake_request(),
                profile_id=uuid.uuid4(),
                repo=repo,
                requesting_user=user,
            )


async def test_get_my_provider_profile_detail_returns_context(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    profile_id, *_ = await _seed_profile(db_test_session_manager, user_id=user.id)

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        context = await handle_get_my_provider_profile_detail(
            request=_fake_request(), repo=repo, requesting_user=user
        )
        assert context["profile"].id == profile_id


async def test_get_my_provider_profile_detail_404_when_user_has_no_profile(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        with pytest.raises(NotFoundError):
            await handle_get_my_provider_profile_detail(
                request=_fake_request(), repo=repo, requesting_user=user
            )


# --- handle_create_profile ----------------------------------------------


async def test_create_profile_persists_row_and_writes_audit(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    payload = _profile_create_payload()

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        created = await handle_create_profile(payload, repo, audit_repo, user)

    assert created.user_id == user.id
    assert created.practice_name == "Acme Health"

    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider_profile",
        resource_id=created.id,
    )
    assert len(rows) == 1
    assert rows[0].action == AuditAction.CREATE_PROVIDER_PROFILE
    assert rows[0].actor_id == user.id
    assert rows[0].before is None
    assert rows[0].after["practice_name"] == "Acme Health"


async def test_create_profile_with_inline_children_captures_them_in_audit(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    payload = _profile_create_payload(
        licensures=[
            ProviderLicensureCreate(
                license_type="lcsw", license_number="L-1", issuing_state="IL"
            )
        ],
        educations=[
            ProviderEducationCreate(education_type="msw", institution="State U")
        ],
        certifications=[
            ProviderCertificationCreate(
                certification_type="emdr", certifying_body="EMDRIA"
            )
        ],
    )

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        created = await handle_create_profile(payload, repo, audit_repo, user)

    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider_profile",
        resource_id=created.id,
    )
    assert len(rows) == 1
    after = rows[0].after
    assert len(after["licensures"]) == 1
    assert after["licensures"][0]["license_number"] == "L-1"
    assert len(after["educations"]) == 1
    assert len(after["certifications"]) == 1

    # Sub-rows actually persisted, too.
    async with db_test_session_manager() as session:
        licensures = (
            (
                await session.execute(
                    select(ProviderLicensure).filter(
                        ProviderLicensure.profile_id == created.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(licensures) == 1


async def test_create_profile_400_when_user_already_has_one(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    await _seed_profile(db_test_session_manager, user_id=user.id)

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        with pytest.raises(BadRequestError):
            await handle_create_profile(
                _profile_create_payload(), repo, audit_repo, user
            )


# --- handle_update_profile ----------------------------------------------


async def test_update_profile_updates_fields_and_writes_audit(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    profile_id, *_ = await _seed_profile(db_test_session_manager, user_id=user.id)

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        updated = await handle_update_profile(
            profile_id,
            ProviderProfileUpdate(practice_name="New Name"),
            repo,
            audit_repo,
            user,
        )

    assert updated.practice_name == "New Name"
    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider_profile",
        resource_id=profile_id,
    )
    assert len(rows) == 1
    assert rows[0].action == AuditAction.UPDATE_PROVIDER_PROFILE
    assert rows[0].before["practice_name"] == "Acme Health"
    assert rows[0].after["practice_name"] == "New Name"


async def test_update_profile_403_for_non_owner(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner = await _seed_user(db_test_session_manager)
    intruder = await _seed_user(db_test_session_manager)
    profile_id, *_ = await _seed_profile(db_test_session_manager, user_id=owner.id)

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        with pytest.raises(ForbiddenError):
            await handle_update_profile(
                profile_id,
                ProviderProfileUpdate(practice_name="Hijacked"),
                repo,
                audit_repo,
                intruder,
            )


async def test_update_profile_succeeds_for_superuser(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner = await _seed_user(db_test_session_manager)
    admin = await _seed_user(db_test_session_manager, is_superuser=True)
    profile_id, *_ = await _seed_profile(db_test_session_manager, user_id=owner.id)

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        updated = await handle_update_profile(
            profile_id,
            ProviderProfileUpdate(practice_name="By Admin"),
            repo,
            audit_repo,
            admin,
        )

    assert updated.practice_name == "By Admin"
    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider_profile",
        resource_id=profile_id,
    )
    assert rows[0].actor_id == admin.id


async def test_update_profile_404_for_unknown_id(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        with pytest.raises(NotFoundError):
            await handle_update_profile(
                uuid.uuid4(),
                ProviderProfileUpdate(practice_name="x"),
                repo,
                audit_repo,
                user,
            )


# --- handle_delete_profile ----------------------------------------------


async def test_delete_profile_removes_row_and_writes_audit(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    profile_id, licensure_id, *_ = await _seed_profile(
        db_test_session_manager, user_id=user.id, with_licensure=True
    )

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        await handle_delete_profile(profile_id, repo, audit_repo, user)

    # Profile and cascaded sub-row both gone.
    async with db_test_session_manager() as session:
        assert (
            await session.execute(
                select(ProviderProfile).filter(ProviderProfile.id == profile_id)
            )
        ).scalars().first() is None
        assert (
            await session.execute(
                select(ProviderLicensure).filter(ProviderLicensure.id == licensure_id)
            )
        ).scalars().first() is None

    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider_profile",
        resource_id=profile_id,
    )
    assert len(rows) == 1
    assert rows[0].action == AuditAction.DELETE_PROVIDER_PROFILE
    assert rows[0].after is None
    assert len(rows[0].before["licensures"]) == 1


async def test_delete_profile_403_for_non_owner(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner = await _seed_user(db_test_session_manager)
    intruder = await _seed_user(db_test_session_manager)
    profile_id, *_ = await _seed_profile(db_test_session_manager, user_id=owner.id)

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        with pytest.raises(ForbiddenError):
            await handle_delete_profile(profile_id, repo, audit_repo, intruder)


# --- Licensure handlers -------------------------------------------------


async def test_create_licensure_attaches_to_profile_and_audits(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    profile_id, *_ = await _seed_profile(db_test_session_manager, user_id=user.id)

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        created = await handle_create_licensure(
            profile_id,
            ProviderLicensureCreate(
                license_type="lcsw", license_number="L-99", issuing_state="IL"
            ),
            repo,
            audit_repo,
            user,
        )

    assert created.profile_id == profile_id
    assert created.license_number == "L-99"
    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider_licensure",
        resource_id=created.id,
    )
    assert len(rows) == 1
    assert rows[0].action == AuditAction.CREATE_LICENSURE


async def test_create_licensure_403_for_non_owner(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner = await _seed_user(db_test_session_manager)
    intruder = await _seed_user(db_test_session_manager)
    profile_id, *_ = await _seed_profile(db_test_session_manager, user_id=owner.id)

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        with pytest.raises(ForbiddenError):
            await handle_create_licensure(
                profile_id,
                ProviderLicensureCreate(
                    license_type="lcsw", license_number="L-99", issuing_state="IL"
                ),
                repo,
                audit_repo,
                intruder,
            )


async def test_update_licensure_audits_before_after(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    profile_id, licensure_id, *_ = await _seed_profile(
        db_test_session_manager, user_id=user.id, with_licensure=True
    )

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        updated = await handle_update_licensure(
            profile_id,
            licensure_id,
            ProviderLicensureUpdate(license_number="L-NEW"),
            repo,
            audit_repo,
            user,
        )

    assert updated.license_number == "L-NEW"
    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider_licensure",
        resource_id=licensure_id,
    )
    assert rows[0].action == AuditAction.UPDATE_LICENSURE
    assert rows[0].before["license_number"] == "L-12345"
    assert rows[0].after["license_number"] == "L-NEW"


async def test_update_licensure_404_when_sub_row_belongs_to_other_profile(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user_a = await _seed_user(db_test_session_manager)
    user_b = await _seed_user(db_test_session_manager)
    profile_a, *_ = await _seed_profile(db_test_session_manager, user_id=user_a.id)
    profile_b, lic_b, *_ = await _seed_profile(
        db_test_session_manager, user_id=user_b.id, with_licensure=True
    )

    # user_a tries to update lic_b via profile_a — should 404, not 403, since
    # the URL claims a sub-row that doesn't belong to the named parent.
    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        with pytest.raises(NotFoundError):
            await handle_update_licensure(
                profile_a,
                lic_b,
                ProviderLicensureUpdate(license_number="L-X"),
                repo,
                audit_repo,
                user_a,
            )


async def test_delete_licensure_removes_row_and_audits(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    profile_id, licensure_id, *_ = await _seed_profile(
        db_test_session_manager, user_id=user.id, with_licensure=True
    )

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        await handle_delete_licensure(profile_id, licensure_id, repo, audit_repo, user)

    async with db_test_session_manager() as session:
        assert (
            await session.execute(
                select(ProviderLicensure).filter(ProviderLicensure.id == licensure_id)
            )
        ).scalars().first() is None

    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider_licensure",
        resource_id=licensure_id,
    )
    assert rows[0].action == AuditAction.DELETE_LICENSURE
    assert rows[0].after is None


# --- Education + certification smoke tests ------------------------------


async def test_create_education_attaches_and_audits(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    profile_id, *_ = await _seed_profile(db_test_session_manager, user_id=user.id)

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        created = await handle_create_education(
            profile_id,
            ProviderEducationCreate(education_type="phd", institution="Some U"),
            repo,
            audit_repo,
            user,
        )

    assert created.profile_id == profile_id
    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider_education",
        resource_id=created.id,
    )
    assert rows[0].action == AuditAction.CREATE_EDUCATION


async def test_update_education_audits(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    profile_id, _, education_id, _ = await _seed_profile(
        db_test_session_manager, user_id=user.id, with_education=True
    )

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        updated = await handle_update_education(
            profile_id,
            education_id,
            ProviderEducationUpdate(institution="New U"),
            repo,
            audit_repo,
            user,
        )

    assert updated.institution == "New U"
    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider_education",
        resource_id=education_id,
    )
    assert rows[0].action == AuditAction.UPDATE_EDUCATION


async def test_delete_education_removes_and_audits(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    profile_id, _, education_id, _ = await _seed_profile(
        db_test_session_manager, user_id=user.id, with_education=True
    )

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        await handle_delete_education(profile_id, education_id, repo, audit_repo, user)

    async with db_test_session_manager() as session:
        assert (
            await session.execute(
                select(ProviderEducation).filter(ProviderEducation.id == education_id)
            )
        ).scalars().first() is None
    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider_education",
        resource_id=education_id,
    )
    assert rows[0].action == AuditAction.DELETE_EDUCATION


async def test_create_certification_attaches_and_audits(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    profile_id, *_ = await _seed_profile(db_test_session_manager, user_id=user.id)

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        created = await handle_create_certification(
            profile_id,
            ProviderCertificationCreate(
                certification_type="emdr", certifying_body="EMDRIA"
            ),
            repo,
            audit_repo,
            user,
        )

    assert created.profile_id == profile_id
    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider_certification",
        resource_id=created.id,
    )
    assert rows[0].action == AuditAction.CREATE_CERTIFICATION


async def test_update_certification_audits(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    profile_id, _, _, certification_id = await _seed_profile(
        db_test_session_manager, user_id=user.id, with_certification=True
    )

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        updated = await handle_update_certification(
            profile_id,
            certification_id,
            ProviderCertificationUpdate(certifying_body="New Body"),
            repo,
            audit_repo,
            user,
        )

    assert updated.certifying_body == "New Body"
    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider_certification",
        resource_id=certification_id,
    )
    assert rows[0].action == AuditAction.UPDATE_CERTIFICATION


async def test_delete_certification_removes_and_audits(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    profile_id, _, _, certification_id = await _seed_profile(
        db_test_session_manager, user_id=user.id, with_certification=True
    )

    async with db_test_session_manager() as session:
        repo = ProviderProfileRepository(session)
        audit_repo = AuditRepository(session)
        await handle_delete_certification(
            profile_id, certification_id, repo, audit_repo, user
        )

    async with db_test_session_manager() as session:
        assert (
            await session.execute(
                select(ProviderCertification).filter(
                    ProviderCertification.id == certification_id
                )
            )
        ).scalars().first() is None
    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider_certification",
        resource_id=certification_id,
    )
    assert rows[0].action == AuditAction.DELETE_CERTIFICATION
