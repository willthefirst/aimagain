"""Tests for provider orchestration handlers.

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

from src.api.common.exceptions import ForbiddenError, NotFoundError
from src.logic.audit import AuditAction
from src.logic.providers.provider_processing import (
    handle_create_certification,
    handle_create_education,
    handle_create_licensure,
    handle_create_provider,
    handle_get_provider_detail,
    handle_list_providers,
    handle_list_user_providers,
    handle_update_certification,
    handle_update_education,
    handle_update_licensure,
    handle_update_provider,
)
from src.models import (
    AuditLog,
    ProviderLicensure,
    User,
)
from src.repositories.audit_repository import AuditRepository
from src.repositories.favorites.user_favorite_repository import UserFavoriteRepository
from src.repositories.providers.provider_repository import ProviderRepository
from src.repositories.users.user_repository import UserRepository
from src.schemas.providers.provider import (
    ProviderCertificationCreate,
    ProviderCertificationUpdate,
    ProviderCreate,
    ProviderEducationCreate,
    ProviderEducationUpdate,
    ProviderLicensureCreate,
    ProviderLicensureUpdate,
    ProviderUpdate,
)
from tests.helpers import (
    create_test_user,
    make_provider,
    make_provider_certification,
    make_provider_education,
    make_provider_licensure,
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


async def _seed_provider(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    with_licensure: bool = False,
    with_education: bool = False,
    with_certification: bool = False,
) -> tuple[uuid.UUID, uuid.UUID | None, uuid.UUID | None, uuid.UUID | None]:
    provider = make_provider(owner_id=user_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)
        await session.refresh(provider)
        provider_id = provider.id

    licensure_id: uuid.UUID | None = None
    education_id: uuid.UUID | None = None
    certification_id: uuid.UUID | None = None
    async with db_test_session_manager() as session:
        async with session.begin():
            if with_licensure:
                lic = make_provider_licensure(provider_id=provider_id)
                session.add(lic)
            if with_education:
                edu = make_provider_education(provider_id=provider_id)
                session.add(edu)
            if with_certification:
                cert = make_provider_certification(provider_id=provider_id)
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

    return provider_id, licensure_id, education_id, certification_id


def _provider_create_payload(**overrides) -> ProviderCreate:
    base = dict(
        practice_name="Acme Health",
        location_city="Springfield",
        location_state="IL",
        location_zip="62701",
        in_person_sessions="yes",
        virtual_sessions="no",
    )
    base.update(overrides)
    return ProviderCreate(**base)


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


# --- Provider reads -------------------------------------------------------


async def test_list_providers_returns_persisted_rows(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user_a = await _seed_user(db_test_session_manager)
    user_b = await _seed_user(db_test_session_manager)
    await _seed_provider(db_test_session_manager, user_id=user_a.id)
    await _seed_provider(db_test_session_manager, user_id=user_b.id)

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        context = await handle_list_providers(request=_fake_request(), repo=repo)
        assert len(context["providers"]) == 2
        assert context["selected_license_type"] is None
        assert context["selected_issuing_state"] is None


async def test_list_providers_filters_by_license_type(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user_a = await _seed_user(db_test_session_manager)
    user_b = await _seed_user(db_test_session_manager)
    provider_a, *_ = await _seed_provider(
        db_test_session_manager, user_id=user_a.id, with_licensure=True
    )
    provider_b, *_ = await _seed_provider(db_test_session_manager, user_id=user_b.id)
    # Add a non-matching licensure to provider_b
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                make_provider_licensure(provider_id=provider_b, license_type="lpc")
            )

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        context = await handle_list_providers(
            request=_fake_request(), repo=repo, license_type="lcsw"
        )
        assert [p.id for p in context["providers"]] == [provider_a]
        assert context["selected_license_type"] == "lcsw"


async def test_get_provider_detail_returns_context(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    provider_id, *_ = await _seed_provider(db_test_session_manager, user_id=user.id)

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        context = await handle_get_provider_detail(
            request=_fake_request(),
            provider_id=provider_id,
            repo=repo,
            user_favorite_repo=UserFavoriteRepository(session),
            requesting_user=user,
        )
        assert context["provider"].id == provider_id
        assert context["current_user"] is user
        assert "request" in context
        # Owner viewing own provider → can_edit True. Non-owner / admin
        # cases are exercised at the route level
        # (test_get_provider_hides_edit_link_for_non_owner et al.).
        assert context["can_edit"] is True
        # `is_favorited` is a per-viewer derived field; the owner here
        # has not favorited their own provider.
        assert context["is_favorited"] is False


async def test_get_provider_detail_404_for_unknown_id(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        with pytest.raises(NotFoundError):
            await handle_get_provider_detail(
                request=_fake_request(),
                provider_id=uuid.uuid4(),
                repo=repo,
                user_favorite_repo=UserFavoriteRepository(session),
                requesting_user=user,
            )


async def test_get_provider_detail_is_favorited_true_when_self_favorited(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A viewer who has favorited the provider sees `is_favorited=True`."""
    user = await _seed_user(db_test_session_manager)
    other = await _seed_user(db_test_session_manager)
    provider_id, *_ = await _seed_provider(db_test_session_manager, user_id=other.id)

    async with db_test_session_manager() as session:
        fav_repo = UserFavoriteRepository(session)
        await fav_repo.add_favorite(user_id=user.id, provider_id=provider_id)
        await session.commit()

    async with db_test_session_manager() as session:
        context = await handle_get_provider_detail(
            request=_fake_request(),
            provider_id=provider_id,
            repo=ProviderRepository(session),
            user_favorite_repo=UserFavoriteRepository(session),
            requesting_user=user,
        )
        assert context["is_favorited"] is True


async def test_get_provider_detail_is_favorited_false_for_anonymous_viewer(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A `None` `requesting_user` never sees `is_favorited=True` — the
    flag is meaningless without an actor."""
    other = await _seed_user(db_test_session_manager)
    provider_id, *_ = await _seed_provider(db_test_session_manager, user_id=other.id)

    async with db_test_session_manager() as session:
        context = await handle_get_provider_detail(
            request=_fake_request(),
            provider_id=provider_id,
            repo=ProviderRepository(session),
            user_favorite_repo=UserFavoriteRepository(session),
            requesting_user=None,
        )
        assert context["is_favorited"] is False


# --- handle_list_user_providers --------------------------------


async def test_list_user_providers_self_returns_owned(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    first_id, *_ = await _seed_provider(db_test_session_manager, user_id=user.id)
    second_id, *_ = await _seed_provider(db_test_session_manager, user_id=user.id)

    async with db_test_session_manager() as session:
        provider_repo = ProviderRepository(session)
        user_repo = UserRepository(session)
        context = await handle_list_user_providers(
            request=_fake_request(),
            user_id=user.id,
            repo=provider_repo,
            user_repo=user_repo,
            requesting_user=user,
        )

    assert context["is_self"] is True
    assert context["target_user"].id == user.id
    assert {p.id for p in context["providers"]} == {first_id, second_id}


async def test_list_user_providers_self_returns_empty_when_none(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        provider_repo = ProviderRepository(session)
        user_repo = UserRepository(session)
        context = await handle_list_user_providers(
            request=_fake_request(),
            user_id=user.id,
            repo=provider_repo,
            user_repo=user_repo,
            requesting_user=user,
        )

    assert context["is_self"] is True
    assert list(context["providers"]) == []


async def test_list_user_providers_admin_can_view_anyone(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    target = await _seed_user(db_test_session_manager)
    admin = await _seed_user(db_test_session_manager, is_superuser=True)
    provider_id, *_ = await _seed_provider(db_test_session_manager, user_id=target.id)

    async with db_test_session_manager() as session:
        provider_repo = ProviderRepository(session)
        user_repo = UserRepository(session)
        context = await handle_list_user_providers(
            request=_fake_request(),
            user_id=target.id,
            repo=provider_repo,
            user_repo=user_repo,
            requesting_user=admin,
        )

    assert context["is_self"] is False
    assert context["target_user"].id == target.id
    assert [p.id for p in context["providers"]] == [provider_id]


async def test_list_user_providers_non_admin_cannot_view_other(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    target = await _seed_user(db_test_session_manager)
    other = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        provider_repo = ProviderRepository(session)
        user_repo = UserRepository(session)
        with pytest.raises(ForbiddenError):
            await handle_list_user_providers(
                request=_fake_request(),
                user_id=target.id,
                repo=provider_repo,
                user_repo=user_repo,
                requesting_user=other,
            )


async def test_list_user_providers_404_when_target_user_missing(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    admin = await _seed_user(db_test_session_manager, is_superuser=True)

    async with db_test_session_manager() as session:
        provider_repo = ProviderRepository(session)
        user_repo = UserRepository(session)
        with pytest.raises(NotFoundError):
            await handle_list_user_providers(
                request=_fake_request(),
                user_id=uuid.uuid4(),
                repo=provider_repo,
                user_repo=user_repo,
                requesting_user=admin,
            )


# --- handle_create_provider ----------------------------------------------


# PHASE2_REDUNDANT: framework-shaped — generic mount_create + audit row.
async def test_create_provider_persists_row_and_writes_audit(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    payload = _provider_create_payload()

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        audit_repo = AuditRepository(session)
        created = await handle_create_provider(payload, repo, audit_repo, user)

    assert created.owner_id == user.id
    assert created.practice_name == "Acme Health"

    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider",
        resource_id=created.id,
    )
    assert len(rows) == 1
    assert rows[0].action == AuditAction.CREATE_PROVIDER
    assert rows[0].actor_id == user.id
    assert rows[0].before is None
    assert rows[0].after["practice_name"] == "Acme Health"


async def test_create_provider_with_inline_children_captures_them_in_audit(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    payload = _provider_create_payload(
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
        repo = ProviderRepository(session)
        audit_repo = AuditRepository(session)
        created = await handle_create_provider(payload, repo, audit_repo, user)

    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider",
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
                        ProviderLicensure.provider_id == created.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(licensures) == 1


async def test_create_provider_allows_multiple_per_user(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A user may own multiple providers. The handler creates a second provider
    successfully without surfacing the previously-enforced 1:1 rejection."""
    user = await _seed_user(db_test_session_manager)
    first_id, *_ = await _seed_provider(db_test_session_manager, user_id=user.id)

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        audit_repo = AuditRepository(session)
        second = await handle_create_provider(
            _provider_create_payload(practice_name="Second Practice"),
            repo,
            audit_repo,
            user,
        )

    assert second.id != first_id
    assert second.owner_id == user.id
    assert second.practice_name == "Second Practice"


# --- handle_update_provider ----------------------------------------------


# PHASE2_REDUNDANT: framework-shaped — generic mount_update + audit row.
async def test_update_provider_updates_fields_and_writes_audit(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    provider_id, *_ = await _seed_provider(db_test_session_manager, user_id=user.id)

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        audit_repo = AuditRepository(session)
        updated = await handle_update_provider(
            provider_id,
            ProviderUpdate(practice_name="New Name"),
            repo,
            audit_repo,
            user,
        )

    assert updated.practice_name == "New Name"
    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider",
        resource_id=provider_id,
    )
    assert len(rows) == 1
    assert rows[0].action == AuditAction.UPDATE_PROVIDER
    assert rows[0].before["practice_name"] == "Acme Health"
    assert rows[0].after["practice_name"] == "New Name"


# PHASE2_REDUNDANT: framework-shaped — write_authz wiring on mount_update.
async def test_update_provider_403_for_non_owner(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner = await _seed_user(db_test_session_manager)
    intruder = await _seed_user(db_test_session_manager)
    provider_id, *_ = await _seed_provider(db_test_session_manager, user_id=owner.id)

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        audit_repo = AuditRepository(session)
        with pytest.raises(ForbiddenError):
            await handle_update_provider(
                provider_id,
                ProviderUpdate(practice_name="Hijacked"),
                repo,
                audit_repo,
                intruder,
            )


async def test_update_provider_succeeds_for_superuser(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner = await _seed_user(db_test_session_manager)
    admin = await _seed_user(db_test_session_manager, is_superuser=True)
    provider_id, *_ = await _seed_provider(db_test_session_manager, user_id=owner.id)

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        audit_repo = AuditRepository(session)
        updated = await handle_update_provider(
            provider_id,
            ProviderUpdate(practice_name="By Admin"),
            repo,
            audit_repo,
            admin,
        )

    assert updated.practice_name == "By Admin"
    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider",
        resource_id=provider_id,
    )
    assert rows[0].actor_id == admin.id


async def test_update_provider_404_for_unknown_id(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        audit_repo = AuditRepository(session)
        with pytest.raises(NotFoundError):
            await handle_update_provider(
                uuid.uuid4(),
                ProviderUpdate(practice_name="x"),
                repo,
                audit_repo,
                user,
            )


# --- Licensure handlers -------------------------------------------------


# PHASE2_REDUNDANT: framework-shaped — subrow mount_create + parent-chain audit.
async def test_create_licensure_attaches_to_provider_and_audits(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    provider_id, *_ = await _seed_provider(db_test_session_manager, user_id=user.id)

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        audit_repo = AuditRepository(session)
        created = await handle_create_licensure(
            provider_id,
            ProviderLicensureCreate(
                license_type="lcsw", license_number="L-99", issuing_state="IL"
            ),
            repo,
            audit_repo,
            user,
        )

    assert created.provider_id == provider_id
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
    provider_id, *_ = await _seed_provider(db_test_session_manager, user_id=owner.id)

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        audit_repo = AuditRepository(session)
        with pytest.raises(ForbiddenError):
            await handle_create_licensure(
                provider_id,
                ProviderLicensureCreate(
                    license_type="lcsw", license_number="L-99", issuing_state="IL"
                ),
                repo,
                audit_repo,
                intruder,
            )


# PHASE2_REDUNDANT: framework-shaped — subrow mount_update + before/after audit shape.
async def test_update_licensure_audits_before_after(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    provider_id, licensure_id, *_ = await _seed_provider(
        db_test_session_manager, user_id=user.id, with_licensure=True
    )

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        audit_repo = AuditRepository(session)
        updated = await handle_update_licensure(
            provider_id,
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


async def test_update_licensure_404_when_sub_row_belongs_to_other_provider(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user_a = await _seed_user(db_test_session_manager)
    user_b = await _seed_user(db_test_session_manager)
    provider_a, *_ = await _seed_provider(db_test_session_manager, user_id=user_a.id)
    provider_b, lic_b, *_ = await _seed_provider(
        db_test_session_manager, user_id=user_b.id, with_licensure=True
    )

    # user_a tries to update lic_b via provider_a — should 404, not 403, since
    # the URL claims a sub-row that doesn't belong to the named parent.
    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        audit_repo = AuditRepository(session)
        with pytest.raises(NotFoundError):
            await handle_update_licensure(
                provider_a,
                lic_b,
                ProviderLicensureUpdate(license_number="L-X"),
                repo,
                audit_repo,
                user_a,
            )


# --- Education + certification smoke tests ------------------------------


async def test_create_education_attaches_and_audits(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    provider_id, *_ = await _seed_provider(db_test_session_manager, user_id=user.id)

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        audit_repo = AuditRepository(session)
        created = await handle_create_education(
            provider_id,
            ProviderEducationCreate(education_type="phd", institution="Some U"),
            repo,
            audit_repo,
            user,
        )

    assert created.provider_id == provider_id
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
    provider_id, _, education_id, _ = await _seed_provider(
        db_test_session_manager, user_id=user.id, with_education=True
    )

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        audit_repo = AuditRepository(session)
        updated = await handle_update_education(
            provider_id,
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


async def test_create_certification_attaches_and_audits(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    provider_id, *_ = await _seed_provider(db_test_session_manager, user_id=user.id)

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        audit_repo = AuditRepository(session)
        created = await handle_create_certification(
            provider_id,
            ProviderCertificationCreate(
                certification_type="emdr", certifying_body="EMDRIA"
            ),
            repo,
            audit_repo,
            user,
        )

    assert created.provider_id == provider_id
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
    provider_id, _, _, certification_id = await _seed_provider(
        db_test_session_manager, user_id=user.id, with_certification=True
    )

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        audit_repo = AuditRepository(session)
        updated = await handle_update_certification(
            provider_id,
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
