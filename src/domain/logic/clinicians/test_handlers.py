"""Tests for clinician orchestration handlers.

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

from src.domain.logic.clinicians.handlers import (
    clinician_detail_extras,
    clinician_form_extras,
    handle_list_user_clinicians,
)
from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.clinicians.schema import (
    ClinicianCertificationCreate,
    ClinicianCreate,
    ClinicianEducationCreate,
    ClinicianLicensureCreate,
)
from src.domain.logic.favorites.repository import UserFavoriteRepository
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.users.repository import UserRepository
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import (
    Clinician,
    ClinicianLicensure,
    User,
)
from src.domain.specs.clinician import CLINICIAN_ENTITY
from src.framework.audit.core import AuditAction
from src.framework.audit.log import AuditLog
from src.framework.audit.repository import AuditRepository
from src.framework.dispatch.mounts.create import handle_create
from src.framework.dispatch.mounts.detail import handle_detail
from src.framework.dispatch.mounts.list_ import handle_list
from src.framework.http.exceptions import ForbiddenError, NotFoundError
from tests.helpers import (
    create_test_user,
    make_clinician_certification,
    make_clinician_education,
    make_clinician_licensure,
    make_clinician_with_org,
    make_organization_row,
)

pytestmark = pytest.mark.asyncio


def _fake_request(query_string: bytes = b"") -> Request:
    """Minimal Starlette Request used as a placeholder for handlers that
    forward the request into a template context. `query_string` is
    consumed by `parse_page` / `base_query` when the handler paginates;
    callers that don't care leave the default empty."""
    return Request(
        {
            "type": "http",
            "headers": [],
            "method": "GET",
            "path": "/",
            "query_string": query_string,
        }
    )


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


async def _seed_clinician(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    with_licensure: bool = False,
    with_education: bool = False,
    with_certification: bool = False,
) -> tuple[uuid.UUID, uuid.UUID | None, uuid.UUID | None, uuid.UUID | None]:
    clinician = make_clinician_with_org(owner_id=user_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
        await session.refresh(clinician)
        clinician_id = clinician.id

    licensure_id: uuid.UUID | None = None
    education_id: uuid.UUID | None = None
    certification_id: uuid.UUID | None = None
    async with db_test_session_manager() as session:
        async with session.begin():
            if with_licensure:
                lic = make_clinician_licensure(clinician_id=clinician_id)
                session.add(lic)
            if with_education:
                edu = make_clinician_education(clinician_id=clinician_id)
                session.add(edu)
            if with_certification:
                cert = make_clinician_certification(clinician_id=clinician_id)
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

    return clinician_id, licensure_id, education_id, certification_id


async def _seed_org(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    owner_id: uuid.UUID,
    name: str = "Acme Health",
) -> uuid.UUID:
    """Persist a root Organization and return its id. Clinician create
    payloads require ``org_id`` on the wire (#524); tests seed an Org
    first and reference its id."""
    org = make_organization_row(owner_id=owner_id, name=name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(org)
    return org.id


def _clinician_create_payload(*, org_id: uuid.UUID, **overrides) -> ClinicianCreate:
    base = dict(
        org_id=org_id,
        location_city="Springfield",
        location_state="IL",
        location_zip="62701",
        in_person_sessions="yes",
        virtual_sessions="no",
    )
    base.update(overrides)
    return ClinicianCreate(**base)


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


# --- Clinician reads -------------------------------------------------------


async def test_list_clinicians_returns_persisted_rows(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user_a = await _seed_user(db_test_session_manager)
    user_b = await _seed_user(db_test_session_manager)
    await _seed_clinician(db_test_session_manager, user_id=user_a.id)
    await _seed_clinician(db_test_session_manager, user_id=user_b.id)

    async with db_test_session_manager() as session:
        repo = ClinicianRepository(session)
        context = await handle_list(
            CLINICIAN_ENTITY,
            request=_fake_request(),
            repo=repo,
            requesting_user=None,
            filter_values={"license_type": None, "issuing_state": None},
        )
        # Framework binds `context[spec.url_collection] = items`; the
        # collection key is "clinicians" (spec.name plural).
        assert len(context["clinicians"]) == 2
        assert context["selected_license_type"] is None
        assert context["selected_issuing_state"] is None


async def test_list_clinicians_filters_by_license_type(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user_a = await _seed_user(db_test_session_manager)
    user_b = await _seed_user(db_test_session_manager)
    clinician_a_id, *_ = await _seed_clinician(
        db_test_session_manager, user_id=user_a.id, with_licensure=True
    )
    clinician_b_id, *_ = await _seed_clinician(
        db_test_session_manager, user_id=user_b.id
    )
    # Add a non-matching licensure to clinician_b
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                make_clinician_licensure(
                    clinician_id=clinician_b_id, license_type="lpc"
                )
            )

    async with db_test_session_manager() as session:
        repo = ClinicianRepository(session)
        context = await handle_list(
            CLINICIAN_ENTITY,
            request=_fake_request(),
            repo=repo,
            requesting_user=None,
            filter_values={"license_type": ["lcsw"], "issuing_state": None},
        )
        assert [p.id for p in context["clinicians"]] == [clinician_a_id]
        assert context["selected_license_type"] == ["lcsw"]


async def test_get_clinician_detail_returns_context(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    clinician_id, *_ = await _seed_clinician(db_test_session_manager, user_id=user.id)

    async with db_test_session_manager() as session:
        context = await handle_detail(
            CLINICIAN_ENTITY,
            request=_fake_request(),
            target_id=clinician_id,
            repo=ClinicianRepository(session),
            requesting_user=user,
            extras=clinician_detail_extras,
            extra_kwargs={
                "user_favorite_repo": UserFavoriteRepository(session),
                "verification_repo": VerificationRepository(session),
            },
        )
        # Framework binds `context[spec.name] = target`; the spec name
        # is "clinician".
        assert context["clinician"].id == clinician_id
        assert context["current_user"] is user
        assert "request" in context
        # Owner viewing own clinician → can_edit True. Non-owner / admin
        # cases are exercised at the route level
        # (test_get_clinician_hides_edit_link_for_non_owner et al.).
        assert context["can_edit"] is True
        # `is_favorited` is a per-viewer derived field; the owner here
        # has not favorited their own clinician.
        assert context["is_favorited"] is False
        # No verification run yet → None (#707).
        assert context["verification_status"] is None


async def test_get_clinician_detail_404_for_unknown_id(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        with pytest.raises(NotFoundError):
            await handle_detail(
                CLINICIAN_ENTITY,
                request=_fake_request(),
                target_id=uuid.uuid4(),
                repo=ClinicianRepository(session),
                requesting_user=user,
                extras=clinician_detail_extras,
                extra_kwargs={
                    "user_favorite_repo": UserFavoriteRepository(session),
                    "verification_repo": VerificationRepository(session),
                },
            )


async def test_get_clinician_detail_is_favorited_true_when_self_favorited(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A viewer who has favorited the clinician sees `is_favorited=True`."""
    user = await _seed_user(db_test_session_manager)
    other = await _seed_user(db_test_session_manager)
    clinician_id, *_ = await _seed_clinician(db_test_session_manager, user_id=other.id)

    async with db_test_session_manager() as session:
        fav_repo = UserFavoriteRepository(session)
        await fav_repo.add_favorite(user_id=user.id, clinician_id=clinician_id)
        await session.commit()

    async with db_test_session_manager() as session:
        context = await handle_detail(
            CLINICIAN_ENTITY,
            request=_fake_request(),
            target_id=clinician_id,
            repo=ClinicianRepository(session),
            requesting_user=user,
            extras=clinician_detail_extras,
            extra_kwargs={
                "user_favorite_repo": UserFavoriteRepository(session),
                "verification_repo": VerificationRepository(session),
            },
        )
        assert context["is_favorited"] is True


async def test_get_clinician_detail_is_favorited_false_for_anonymous_viewer(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A `None` `requesting_user` never sees `is_favorited=True` — the
    flag is meaningless without an actor. Today `CLINICIAN_ENTITY.read_user_dep`
    forces auth so this branch is defensive; the test pins the contract
    in case the read dep ever loosens."""
    other = await _seed_user(db_test_session_manager)
    clinician_id, *_ = await _seed_clinician(db_test_session_manager, user_id=other.id)

    async with db_test_session_manager() as session:
        context = await handle_detail(
            CLINICIAN_ENTITY,
            request=_fake_request(),
            target_id=clinician_id,
            repo=ClinicianRepository(session),
            requesting_user=None,
            extras=clinician_detail_extras,
            extra_kwargs={
                "user_favorite_repo": UserFavoriteRepository(session),
                "verification_repo": VerificationRepository(session),
            },
        )
        assert context["is_favorited"] is False


# --- handle_list_user_clinicians --------------------------------


async def test_list_user_clinicians_self_returns_owned(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    clinician_first_id, *_ = await _seed_clinician(
        db_test_session_manager, user_id=user.id
    )
    clinician_second_id, *_ = await _seed_clinician(
        db_test_session_manager, user_id=user.id
    )

    async with db_test_session_manager() as session:
        clinician_repo = ClinicianRepository(session)
        user_repo = UserRepository(session)
        context = await handle_list_user_clinicians(
            request=_fake_request(),
            user_id=user.id,
            repo=clinician_repo,
            user_repo=user_repo,
            requesting_user=user,
        )

    assert context["is_self"] is True
    assert context["target_user"].id == user.id
    assert {p.id for p in context["clinicians"]} == {
        clinician_first_id,
        clinician_second_id,
    }


async def test_list_user_clinicians_self_returns_empty_when_none(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        clinician_repo = ClinicianRepository(session)
        user_repo = UserRepository(session)
        context = await handle_list_user_clinicians(
            request=_fake_request(),
            user_id=user.id,
            repo=clinician_repo,
            user_repo=user_repo,
            requesting_user=user,
        )

    assert context["is_self"] is True
    assert list(context["clinicians"]) == []


async def test_list_user_clinicians_admin_can_view_anyone(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    target = await _seed_user(db_test_session_manager)
    admin = await _seed_user(db_test_session_manager, is_superuser=True)
    clinician_id, *_ = await _seed_clinician(db_test_session_manager, user_id=target.id)

    async with db_test_session_manager() as session:
        clinician_repo = ClinicianRepository(session)
        user_repo = UserRepository(session)
        context = await handle_list_user_clinicians(
            request=_fake_request(),
            user_id=target.id,
            repo=clinician_repo,
            user_repo=user_repo,
            requesting_user=admin,
        )

    assert context["is_self"] is False
    assert context["target_user"].id == target.id
    assert [p.id for p in context["clinicians"]] == [clinician_id]


async def test_list_user_clinicians_non_admin_cannot_view_other(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    target = await _seed_user(db_test_session_manager)
    other = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        clinician_repo = ClinicianRepository(session)
        user_repo = UserRepository(session)
        with pytest.raises(ForbiddenError):
            await handle_list_user_clinicians(
                request=_fake_request(),
                user_id=target.id,
                repo=clinician_repo,
                user_repo=user_repo,
                requesting_user=other,
            )


async def test_list_user_clinicians_404_when_target_user_missing(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    admin = await _seed_user(db_test_session_manager, is_superuser=True)

    async with db_test_session_manager() as session:
        clinician_repo = ClinicianRepository(session)
        user_repo = UserRepository(session)
        with pytest.raises(NotFoundError):
            await handle_list_user_clinicians(
                request=_fake_request(),
                user_id=uuid.uuid4(),
                repo=clinician_repo,
                user_repo=user_repo,
                requesting_user=admin,
            )


# --- handle_create (clinician, via the generic framework) -----------------


# Clinician create goes through the framework's `handle_create`. The
# inline-children loop now lives in `_generic.py`, driven by
# `CLINICIAN_ENTITY.children`.
async def test_create_clinician_persists_row_and_writes_audit(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    org_id = await _seed_org(db_test_session_manager, owner_id=user.id)
    payload = _clinician_create_payload(org_id=org_id)

    async with db_test_session_manager() as session:
        repo = ClinicianRepository(session)
        audit_repo = AuditRepository(session)
        created = await handle_create(
            CLINICIAN_ENTITY,
            payload=payload,
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=user,
        )

    assert created.owner_id == user.id
    assert created.org_id == org_id
    assert created.org.name == "Acme Health"

    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="clinician",
        resource_id=created.id,
    )
    assert len(rows) == 1
    assert rows[0].action == AuditAction.CREATE_CLINICIAN
    assert rows[0].actor_id == user.id
    assert rows[0].before is None
    # The audit snapshot mirrors `ClinicianRead` — `org_name` is the
    # practice's display name post-#524.
    assert rows[0].after["org_name"] == "Acme Health"
    assert rows[0].after["org_id"] == str(org_id)


async def test_create_clinician_with_inline_children_captures_them_in_audit(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    org_id = await _seed_org(db_test_session_manager, owner_id=user.id)
    payload = _clinician_create_payload(
        org_id=org_id,
        licensures=[
            ClinicianLicensureCreate(
                license_type="lcsw", license_number="L-1", issuing_state="IL"
            )
        ],
        educations=[
            ClinicianEducationCreate(education_type="msw", institution="State U")
        ],
        certifications=[
            ClinicianCertificationCreate(
                certification_type="emdr", certifying_body="EMDRIA"
            )
        ],
    )

    async with db_test_session_manager() as session:
        repo = ClinicianRepository(session)
        audit_repo = AuditRepository(session)
        created = await handle_create(
            CLINICIAN_ENTITY,
            payload=payload,
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=user,
        )

    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="clinician",
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
                    select(ClinicianLicensure).filter(
                        ClinicianLicensure.clinician_id == created.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(licensures) == 1


async def test_create_clinician_allows_multiple_per_user(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A user may own multiple clinicians. The handler creates a second clinician
    successfully without surfacing the previously-enforced 1:1 rejection."""
    user = await _seed_user(db_test_session_manager)
    clinician_first_id, *_ = await _seed_clinician(
        db_test_session_manager, user_id=user.id
    )
    second_org_id = await _seed_org(
        db_test_session_manager, owner_id=user.id, name="Second Practice"
    )

    async with db_test_session_manager() as session:
        repo = ClinicianRepository(session)
        audit_repo = AuditRepository(session)
        second = await handle_create(
            CLINICIAN_ENTITY,
            payload=_clinician_create_payload(org_id=second_org_id),
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=user,
        )

    assert second.id != clinician_first_id
    assert second.owner_id == user.id
    assert second.org.name == "Second Practice"


# --- clinician_form_extras (#533) -----------------------------------------


async def test_clinician_form_extras_returns_owners_visible_orgs(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Owner sees only the Orgs they own. Mirrors the previous
    `handle_get_clinician_new_form` behavior, now provided by the
    framework via `form_extras_path`."""
    owner = await _seed_user(db_test_session_manager)
    stranger = await _seed_user(db_test_session_manager)
    owned_id = await _seed_org(db_test_session_manager, owner_id=owner.id, name="Mine")
    await _seed_org(db_test_session_manager, owner_id=stranger.id, name="Other")

    async with db_test_session_manager() as session:
        org_repo = OrganizationRepository(session)
        # Create path: target is None.
        result = await clinician_form_extras(
            target=None,
            requesting_user=owner,
            organization_repo=org_repo,
        )
        assert [o.id for o in result["orgs"]] == [owned_id]


async def test_clinician_form_extras_superuser_sees_all_orgs(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Superusers see every Org regardless of ownership — same
    semantics as the previous bespoke handler."""
    admin = await _seed_user(db_test_session_manager, is_superuser=True)
    other = await _seed_user(db_test_session_manager)
    await _seed_org(db_test_session_manager, owner_id=admin.id, name="Admin Org")
    await _seed_org(db_test_session_manager, owner_id=other.id, name="Other Org")

    async with db_test_session_manager() as session:
        org_repo = OrganizationRepository(session)
        result = await clinician_form_extras(
            target=None,
            requesting_user=admin,
            organization_repo=org_repo,
        )
        org_names = {o.name for o in result["orgs"]}
        assert "Admin Org" in org_names
        assert "Other Org" in org_names


async def test_clinician_form_extras_edit_path_passes_target(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """On the edit path the framework passes the loaded Clinician as
    `target`. The current implementation doesn't read it, but the
    callable must accept it without complaint — the contract is the
    same on both paths."""
    owner = await _seed_user(db_test_session_manager)
    await _seed_org(db_test_session_manager, owner_id=owner.id, name="Owned")
    clinician_id, *_ = await _seed_clinician(db_test_session_manager, user_id=owner.id)

    async with db_test_session_manager() as session:
        clinician_repo = ClinicianRepository(session)
        clinician = await clinician_repo.get_by_model_id(Clinician, clinician_id)
        org_repo = OrganizationRepository(session)
        result = await clinician_form_extras(
            target=clinician,
            requesting_user=owner,
            organization_repo=org_repo,
        )
        assert "orgs" in result


# --- Admin verification-state axis ---------------------------------------


async def test_set_clinician_verification_state_matched_writes_audit_and_event(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Admin flips a clinician to `matched`. Cache updates,
    `npi_verified_at` is set, a `SET_CLINICIAN_VERIFICATION_STATE`
    audit row lands, and an `admin_verify` Verification event is
    appended."""
    from src.domain.logic.clinicians.handlers import (
        handle_set_clinician_verification_state,
    )
    from src.domain.logic.clinicians.schema import ClinicianVerificationStateUpdate
    from src.domain.models import Verification

    admin = await _seed_user(db_test_session_manager, is_superuser=True)
    owner = await _seed_user(db_test_session_manager)
    clinician_id, *_ = await _seed_clinician(db_test_session_manager, user_id=owner.id)

    async with db_test_session_manager() as session:
        clinician_repo = ClinicianRepository(session)
        verification_repo = VerificationRepository(session)
        audit_repo = AuditRepository(session)
        await handle_set_clinician_verification_state(
            clinician_id=clinician_id,
            payload=ClinicianVerificationStateUpdate(state="matched"),
            repo=clinician_repo,
            verification_repo=verification_repo,
            audit_repo=audit_repo,
            requesting_user=admin,
        )

    async with db_test_session_manager() as session:
        loaded = await session.get(Clinician, clinician_id)
        assert loaded.npi_match_status == "matched"
        assert loaded.npi_verified_at is not None

        rows = await _audit_rows_for(
            db_test_session_manager,
            resource_type=CLINICIAN_ENTITY.audit.type,
            resource_id=clinician_id,
        )
        actions = {r.action for r in rows}
        assert AuditAction.SET_CLINICIAN_VERIFICATION_STATE.value in actions

        events = (
            (
                await session.execute(
                    select(Verification).filter(
                        Verification.clinician_id == clinician_id,
                        Verification.event_type == "admin_verify",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1


async def test_set_clinician_verification_state_mismatch_records_admin_suspend(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    from src.domain.logic.clinicians.handlers import (
        handle_set_clinician_verification_state,
    )
    from src.domain.logic.clinicians.schema import ClinicianVerificationStateUpdate
    from src.domain.models import Verification

    admin = await _seed_user(db_test_session_manager, is_superuser=True)
    owner = await _seed_user(db_test_session_manager)
    clinician_id, *_ = await _seed_clinician(db_test_session_manager, user_id=owner.id)

    async with db_test_session_manager() as session:
        await handle_set_clinician_verification_state(
            clinician_id=clinician_id,
            payload=ClinicianVerificationStateUpdate(state="mismatch"),
            repo=ClinicianRepository(session),
            verification_repo=VerificationRepository(session),
            audit_repo=AuditRepository(session),
            requesting_user=admin,
        )

    async with db_test_session_manager() as session:
        loaded = await session.get(Clinician, clinician_id)
        assert loaded.npi_match_status == "mismatch"
        events = (
            (
                await session.execute(
                    select(Verification).filter(
                        Verification.clinician_id == clinician_id,
                        Verification.event_type == "admin_suspend",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1


async def test_set_clinician_verification_state_pending_clears_verified_at(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Re-queueing to `pending` clears `npi_verified_at` and records
    no Verification event (the row hasn't resolved to anything yet)."""
    import datetime

    from src.domain.logic.clinicians.handlers import (
        handle_set_clinician_verification_state,
    )
    from src.domain.logic.clinicians.schema import ClinicianVerificationStateUpdate
    from src.domain.models import Verification

    admin = await _seed_user(db_test_session_manager, is_superuser=True)
    owner = await _seed_user(db_test_session_manager)
    clinician_id, *_ = await _seed_clinician(db_test_session_manager, user_id=owner.id)

    async with db_test_session_manager() as session:
        async with session.begin():
            row = await session.get(Clinician, clinician_id)
            row.npi_match_status = "matched"
            row.npi_verified_at = datetime.datetime.now(datetime.timezone.utc)

    async with db_test_session_manager() as session:
        await handle_set_clinician_verification_state(
            clinician_id=clinician_id,
            payload=ClinicianVerificationStateUpdate(state="pending"),
            repo=ClinicianRepository(session),
            verification_repo=VerificationRepository(session),
            audit_repo=AuditRepository(session),
            requesting_user=admin,
        )

    async with db_test_session_manager() as session:
        loaded = await session.get(Clinician, clinician_id)
        assert loaded.npi_match_status == "pending"
        assert loaded.npi_verified_at is None
        admin_events = (
            (
                await session.execute(
                    select(Verification).filter(
                        Verification.clinician_id == clinician_id,
                        Verification.event_type.in_(["admin_verify", "admin_suspend"]),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert admin_events == []


async def test_set_clinician_verification_state_non_admin_forbidden(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    from src.domain.logic.clinicians.handlers import (
        handle_set_clinician_verification_state,
    )
    from src.domain.logic.clinicians.schema import ClinicianVerificationStateUpdate

    non_admin = await _seed_user(db_test_session_manager)
    clinician_id, *_ = await _seed_clinician(
        db_test_session_manager, user_id=non_admin.id
    )

    async with db_test_session_manager() as session:
        with pytest.raises(ForbiddenError):
            await handle_set_clinician_verification_state(
                clinician_id=clinician_id,
                payload=ClinicianVerificationStateUpdate(state="matched"),
                repo=ClinicianRepository(session),
                verification_repo=VerificationRepository(session),
                audit_repo=AuditRepository(session),
                requesting_user=non_admin,
            )


async def test_set_clinician_verification_state_404_for_missing(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    from src.domain.logic.clinicians.handlers import (
        handle_set_clinician_verification_state,
    )
    from src.domain.logic.clinicians.schema import ClinicianVerificationStateUpdate

    admin = await _seed_user(db_test_session_manager, is_superuser=True)

    async with db_test_session_manager() as session:
        with pytest.raises(NotFoundError):
            await handle_set_clinician_verification_state(
                clinician_id=uuid.uuid4(),
                payload=ClinicianVerificationStateUpdate(state="matched"),
                repo=ClinicianRepository(session),
                verification_repo=VerificationRepository(session),
                audit_repo=AuditRepository(session),
                requesting_user=admin,
            )


# --- after_create_clinician_verification (post-create hook) ---------------


async def test_after_create_clinician_verification_creates_verification_row(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Happy path: the hook produces one Verification row for the just-
    created clinician and updates the Claim-A denorm cache.

    `nppes_lookup` is patched so no real HTTP call is made; the OIG module
    is pointed at the fixture CSV so it loads correctly.
    """
    from pathlib import Path
    from unittest.mock import AsyncMock, patch

    from src.domain.logic.clinicians.handlers import after_create_clinician_verification
    from src.domain.logic.verifications import oig as oig_module
    from src.domain.logic.verifications.nppes import NppesResult

    leie_fixture = (
        Path(__file__).parent.parent / "verifications" / "test_data" / "leie_sample.csv"
    )
    oig_module._reset_cache_for_tests()

    import os

    old_path = os.environ.get("LEIE_CSV_PATH")
    os.environ["LEIE_CSV_PATH"] = str(leie_fixture)
    try:
        user = await _seed_user(db_test_session_manager)
        org_id = await _seed_org(db_test_session_manager, owner_id=user.id)

        nppes_match = NppesResult(
            found=True, first_name="Jane", last_name="Smith", raw={}
        )

        async with db_test_session_manager() as session:
            repo = ClinicianRepository(session)
            audit_repo = AuditRepository(session)
            verification_repo = VerificationRepository(session)

            clinician = Clinician(
                owner_id=user.id,
                org_id=org_id,
                location_city="Springfield",
                location_state="IL",
                location_zip="62701",
                in_person_sessions="yes",
                virtual_sessions="no",
                first_name="Jane",
                last_name="Smith",
                npi="9999999999",
            )
            created = await repo.create(clinician)

            with patch(
                "src.domain.logic.verifications.handlers.nppes_lookup",
                new=AsyncMock(return_value=nppes_match),
            ):
                await after_create_clinician_verification(
                    row=created,
                    payload=_clinician_create_payload(org_id=org_id),
                    requesting_user=user,
                    verification_repo=verification_repo,
                    clinician_repo=repo,
                    verification_audit_repo=audit_repo,
                )

        async with db_test_session_manager() as session:
            from src.domain.models import Verification

            rows = (
                (
                    await session.execute(
                        select(Verification).filter(
                            Verification.clinician_id == created.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].status == "verified"
            assert rows[0].event_type == "npi_resolved"

            loaded = await session.get(Clinician, created.id)
            assert loaded.npi_match_status == "matched"
    finally:
        if old_path is None:
            os.environ.pop("LEIE_CSV_PATH", None)
        else:
            os.environ["LEIE_CSV_PATH"] = old_path
        oig_module._reset_cache_for_tests()


async def test_after_create_clinician_verification_no_npi_records_skipped(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A clinician without an NPI still gets a Verification row (status=failed,
    nppes_skipped flag) and npi_match_status stays 'none'. nppes_lookup is never called.
    """
    from pathlib import Path
    from unittest.mock import AsyncMock, patch

    from src.domain.logic.clinicians.handlers import after_create_clinician_verification
    from src.domain.logic.verifications import oig as oig_module

    leie_fixture = (
        Path(__file__).parent.parent / "verifications" / "test_data" / "leie_sample.csv"
    )
    oig_module._reset_cache_for_tests()

    import os

    old_path = os.environ.get("LEIE_CSV_PATH")
    os.environ["LEIE_CSV_PATH"] = str(leie_fixture)
    try:
        user = await _seed_user(db_test_session_manager)
        org_id = await _seed_org(db_test_session_manager, owner_id=user.id)

        async with db_test_session_manager() as session:
            repo = ClinicianRepository(session)
            audit_repo = AuditRepository(session)
            verification_repo = VerificationRepository(session)

            clinician = Clinician(
                owner_id=user.id,
                org_id=org_id,
                location_city="Springfield",
                location_state="IL",
                location_zip="62701",
                in_person_sessions="yes",
                virtual_sessions="no",
                npi=None,
            )
            created = await repo.create(clinician)

            nppes_stub = AsyncMock(
                side_effect=AssertionError("nppes_lookup called unexpectedly")
            )
            with patch(
                "src.domain.logic.verifications.handlers.nppes_lookup",
                new=nppes_stub,
            ):
                await after_create_clinician_verification(
                    row=created,
                    payload=_clinician_create_payload(org_id=org_id),
                    requesting_user=user,
                    verification_repo=verification_repo,
                    clinician_repo=repo,
                    verification_audit_repo=audit_repo,
                )
            nppes_stub.assert_not_called()

        async with db_test_session_manager() as session:
            from src.domain.models import Verification

            rows = (
                (
                    await session.execute(
                        select(Verification).filter(
                            Verification.clinician_id == created.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].status == "failed"
            assert "nppes_skipped" in rows[0].flags

            loaded = await session.get(Clinician, created.id)
            assert loaded.npi_match_status == "none"
    finally:
        if old_path is None:
            os.environ.pop("LEIE_CSV_PATH", None)
        else:
            os.environ["LEIE_CSV_PATH"] = old_path
        oig_module._reset_cache_for_tests()


# --- after_update_clinician_verification (re-verify on npi change) -------


async def test_after_update_reverifies_when_npi_changed(monkeypatch):
    """When `npi` is among the changed fields, the update hook delegates to
    the NPI-verification pipeline. (The pipeline mechanics are covered by the
    after_create DB test; this pins the change-gating + delegation.)"""
    from types import SimpleNamespace
    from uuid import uuid4

    from src.domain.logic.clinicians import handlers as h

    seen: dict = {}

    async def _fake_verify(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(h, "after_create_clinician_verification", _fake_verify)

    row = SimpleNamespace(id=uuid4())
    user = SimpleNamespace(id=uuid4())
    await h.after_update_clinician_verification(
        row=row,
        payload=SimpleNamespace(),
        requesting_user=user,
        changed_fields={"npi", "first_name"},
        verification_repo="vr",
        clinician_repo="cr",
        verification_audit_repo="ar",
    )
    assert seen.get("row") is row
    assert seen.get("clinician_repo") == "cr"


async def test_after_update_noop_when_npi_unchanged(monkeypatch):
    """A non-NPI edit (e.g. location only) must NOT re-run NPI verification —
    no needless NPPES lookup."""
    from types import SimpleNamespace
    from uuid import uuid4

    from src.domain.logic.clinicians import handlers as h

    called = False

    async def _fake_verify(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(h, "after_create_clinician_verification", _fake_verify)

    await h.after_update_clinician_verification(
        row=SimpleNamespace(id=uuid4()),
        payload=SimpleNamespace(),
        requesting_user=SimpleNamespace(id=uuid4()),
        changed_fields={"location_city", "location_state"},
        verification_repo="vr",
        clinician_repo="cr",
        verification_audit_repo="ar",
    )
    assert called is False
