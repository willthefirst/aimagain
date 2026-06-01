"""Tests for `OrgRepresentation` create dispatch (validate + after_create).

Per handoff §6 the create-time logic differs by `authority_method`:

* ``authorized_official`` — auto-verify when the user's verified
  Clinician name clears the NPPES AO similarity threshold; reject on
  no match.
* ``domain_email`` — v1 stub; 400.
* ``rep_approval`` — requires the requesting user to be an existing
  verified rep on the same org; row lands at ``verified``.
* ``admin_review`` — row lands at ``pending``.

The dispatch is split across two spec hooks:

* `validate_org_representation_payload` (`payload_authz_path`) runs
  pre-persistence and raises on rejection.
* `after_create_org_representation` (`after_create_path`) runs post-
  persistence and mutates the row's `authority_status` + `approved_by`
  + records the `Verification` event.

These tests exercise each hook directly. The route-level happy path
flowing through the framework's generic create handler is covered
separately in `routes/test_org_representations.py`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.org_representations.handlers import (
    after_create_org_representation,
    validate_org_representation_payload,
)
from src.domain.logic.org_representations.repository import (
    OrgRepresentationRepository,
)
from src.domain.logic.org_representations.schema import OrgRepresentationCreate
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import (
    Organization,
    OrgRepresentation,
    User,
    Verification,
)
from src.framework.audit.repository import AuditRepository
from src.framework.http.exceptions import BadRequestError, ForbiddenError, NotFoundError
from tests.helpers import (
    create_test_user,
    make_clinician_with_org,
    make_organization_row,
)

pytestmark = pytest.mark.asyncio


async def _seed_user_and_org(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    username: str = "actor",
    org_name: str = "Acme Health",
    org_ao_name: str | None = None,
) -> tuple[User, Organization]:
    user = create_test_user(username=username)
    org = make_organization_row(owner_id=user.id, name=org_name)
    if org_ao_name is not None:
        org.authorized_official_name = org_ao_name
        org.npi_match_status = "matched"
        org.org_verified = True
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(org)
    return user, org


async def _seed_verified_clinician(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    owner_id,
    first: str,
    last: str,
):
    async with db_test_session_manager() as session:
        async with session.begin():
            clinician = make_clinician_with_org(
                owner_id=owner_id,
                first_name=first,
                last_name=last,
                npi="1234567890",
            )
            clinician.clinician_verified = True
            clinician.npi_match_status = "matched"
            session.add(clinician)


async def _persist_and_run_after_create(
    db_test_session_manager,
    payload: OrgRepresentationCreate,
    requesting_user: User,
) -> OrgRepresentation:
    """End-to-end runner mirroring what the framework's generic
    create+after_create flow does, but in-process so the tests can
    introspect the row + Verification side effects."""
    async with db_test_session_manager() as session:
        new_row = OrgRepresentation(
            user_id=payload.user_id,
            org_id=payload.org_id,
            role=payload.role,
            authority_method=payload.authority_method,
        )
        repo = OrgRepresentationRepository(session)
        persisted = await repo._persist_new(new_row)
        await after_create_org_representation(
            row=persisted,
            payload=payload,
            requesting_user=requesting_user,
            verification_repo=VerificationRepository(session),
            audit_repo_dep=AuditRepository(session),
        )
        await session.commit()
        return persisted


# ---------- admin_review (the simplest, default path) -------------------


async def test_admin_review_lands_at_pending(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, org = await _seed_user_and_org(db_test_session_manager)
    payload = OrgRepresentationCreate(
        user_id=user.id,
        org_id=org.id,
        role="coordinator",
        authority_method="admin_review",
    )
    async with db_test_session_manager() as session:
        await validate_org_representation_payload(
            payload=payload,
            requesting_user=user,
            org_rep_repo=OrgRepresentationRepository(session),
        )
    new_row = await _persist_and_run_after_create(
        db_test_session_manager, payload, user
    )
    assert new_row.authority_status == "pending"
    assert new_row.approved_by is None


# ---------- authorized_official -----------------------------------------


async def test_authorized_official_happy_path(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, org = await _seed_user_and_org(
        db_test_session_manager, org_ao_name="Jane Doe"
    )
    await _seed_verified_clinician(
        db_test_session_manager, owner_id=user.id, first="Jane", last="Doe"
    )
    async with db_test_session_manager() as session:
        reloaded_user = await session.get(User, user.id)
        payload = OrgRepresentationCreate(
            user_id=reloaded_user.id,
            org_id=org.id,
            role="owner",
            authority_method="authorized_official",
        )
        await validate_org_representation_payload(
            payload=payload,
            requesting_user=reloaded_user,
            org_rep_repo=OrgRepresentationRepository(session),
        )
    new_row = await _persist_and_run_after_create(
        db_test_session_manager, payload, reloaded_user
    )
    assert new_row.authority_status == "verified"
    async with db_test_session_manager() as session:
        events = (
            (
                await session.execute(
                    select(Verification).filter(
                        Verification.org_id == org.id,
                        Verification.event_type == "authority_proven",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1


async def test_authorized_official_rejects_name_mismatch(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, org = await _seed_user_and_org(
        db_test_session_manager, org_ao_name="Jane Doe"
    )
    await _seed_verified_clinician(
        db_test_session_manager,
        owner_id=user.id,
        first="Bartholomew",
        last="Jenkins",
    )
    async with db_test_session_manager() as session:
        reloaded_user = await session.get(User, user.id)
        payload = OrgRepresentationCreate(
            user_id=reloaded_user.id,
            org_id=org.id,
            role="owner",
            authority_method="authorized_official",
        )
        with pytest.raises(BadRequestError, match="Authorized Official"):
            await validate_org_representation_payload(
                payload=payload,
                requesting_user=reloaded_user,
                org_rep_repo=OrgRepresentationRepository(session),
            )


async def test_authorized_official_requires_org_ao_name_cached(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The org's Type-2 NPI must have been verified first so NPPES has
    populated `authorized_official_name`."""
    user, org = await _seed_user_and_org(db_test_session_manager)  # no AO name
    await _seed_verified_clinician(
        db_test_session_manager, owner_id=user.id, first="Jane", last="Doe"
    )
    async with db_test_session_manager() as session:
        reloaded_user = await session.get(User, user.id)
        payload = OrgRepresentationCreate(
            user_id=reloaded_user.id,
            org_id=org.id,
            role="owner",
            authority_method="authorized_official",
        )
        with pytest.raises(BadRequestError, match="no cached Authorized Official"):
            await validate_org_representation_payload(
                payload=payload,
                requesting_user=reloaded_user,
                org_rep_repo=OrgRepresentationRepository(session),
            )


async def test_authorized_official_requires_verified_clinician(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A user with no `clinician_verified=True` clinician can't take
    the AO path — there's no name to match against."""
    user, org = await _seed_user_and_org(
        db_test_session_manager, org_ao_name="Jane Doe"
    )
    async with db_test_session_manager() as session:
        reloaded_user = await session.get(User, user.id)
        payload = OrgRepresentationCreate(
            user_id=reloaded_user.id,
            org_id=org.id,
            role="owner",
            authority_method="authorized_official",
        )
        with pytest.raises(BadRequestError, match="verified clinician profile"):
            await validate_org_representation_payload(
                payload=payload,
                requesting_user=reloaded_user,
                org_rep_repo=OrgRepresentationRepository(session),
            )


# ---------- domain_email v1 stub ----------------------------------------


async def test_domain_email_returns_not_yet_enabled(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, org = await _seed_user_and_org(db_test_session_manager)
    payload = OrgRepresentationCreate(
        user_id=user.id,
        org_id=org.id,
        role="coordinator",
        authority_method="domain_email",
    )
    async with db_test_session_manager() as session:
        with pytest.raises(BadRequestError, match="not yet enabled"):
            await validate_org_representation_payload(
                payload=payload,
                requesting_user=user,
                org_rep_repo=OrgRepresentationRepository(session),
            )


# ---------- rep_approval ------------------------------------------------


async def test_rep_approval_requires_existing_verified_rep_on_org(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The requesting user must already be a verified rep on the target
    org (or be admin)."""
    user, org = await _seed_user_and_org(db_test_session_manager)
    payload = OrgRepresentationCreate(
        user_id=user.id,
        org_id=org.id,
        role="coordinator",
        authority_method="rep_approval",
    )
    async with db_test_session_manager() as session:
        with pytest.raises(ForbiddenError, match="existing verified representative"):
            await validate_org_representation_payload(
                payload=payload,
                requesting_user=user,
                org_rep_repo=OrgRepresentationRepository(session),
            )


async def test_rep_approval_admin_bypass(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Admins bypass the verified-rep-on-org check."""
    user, org = await _seed_user_and_org(db_test_session_manager)
    admin = create_test_user(username=f"admin-{user.id}", is_superuser=True)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(admin)
    payload = OrgRepresentationCreate(
        user_id=user.id,
        org_id=org.id,
        role="coordinator",
        authority_method="rep_approval",
    )
    async with db_test_session_manager() as session:
        await validate_org_representation_payload(
            payload=payload,
            requesting_user=admin,
            org_rep_repo=OrgRepresentationRepository(session),
        )
    new_row = await _persist_and_run_after_create(
        db_test_session_manager, payload, admin
    )
    assert new_row.authority_status == "verified"
    assert new_row.approved_by == admin.id


# ---------- general authz / 404 -----------------------------------------


async def test_user_cant_create_rep_for_someone_else(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, org = await _seed_user_and_org(db_test_session_manager)
    other = create_test_user(username="other")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    payload = OrgRepresentationCreate(
        user_id=other.id,
        org_id=org.id,
        role="coordinator",
        authority_method="admin_review",
    )
    async with db_test_session_manager() as session:
        with pytest.raises(ForbiddenError, match="another user"):
            await validate_org_representation_payload(
                payload=payload,
                requesting_user=user,
                org_rep_repo=OrgRepresentationRepository(session),
            )


async def test_404_for_missing_org(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    import uuid

    user = create_test_user(username="actor")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
    payload = OrgRepresentationCreate(
        user_id=user.id,
        org_id=uuid.uuid4(),
        role="coordinator",
        authority_method="admin_review",
    )
    async with db_test_session_manager() as session:
        with pytest.raises(NotFoundError):
            await validate_org_representation_payload(
                payload=payload,
                requesting_user=user,
                org_rep_repo=OrgRepresentationRepository(session),
            )
