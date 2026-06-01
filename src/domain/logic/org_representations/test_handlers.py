"""Tests for `handle_create_org_representation` authority-method dispatch.

Per handoff §6 the create-time logic differs by `authority_method`:

* ``authorized_official`` — auto-verify when the user's verified
  Clinician name clears the NPPES AO similarity threshold; reject on
  no match.
* ``domain_email`` — v1 stub; 400.
* ``rep_approval`` — requires the requesting user to be an existing
  verified rep on the same org; row lands at ``verified``.
* ``admin_review`` — row lands at ``pending``.

These tests exercise the dispatch directly (handler-level), pinning
each branch's initial `authority_status` + `approved_by` + the
`Verification` event side effect. The route-level happy path is
covered separately in `routes/test_org_representations.py` (added in
the follow-up).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.org_representations.handlers import (
    handle_create_org_representation,
)
from src.domain.logic.org_representations.repository import (
    OrgRepresentationRepository,
)
from src.domain.logic.org_representations.schema import OrgRepresentationCreate
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import (
    Clinician,
    Organization,
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
) -> Clinician:
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
    return clinician


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
        new_row = await handle_create_org_representation(
            payload=payload,
            repo=OrgRepresentationRepository(session),
            verification_repo=VerificationRepository(session),
            audit_repo=AuditRepository(session),
            requesting_user=user,
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
        db_test_session_manager,
        owner_id=user.id,
        first="Jane",
        last="Doe",
    )
    # Refresh `user.clinicians` by reloading the user from the DB.
    async with db_test_session_manager() as session:
        reloaded_user = await session.get(User, user.id)
        payload = OrgRepresentationCreate(
            user_id=reloaded_user.id,
            org_id=org.id,
            role="owner",
            authority_method="authorized_official",
        )
        new_row = await handle_create_org_representation(
            payload=payload,
            repo=OrgRepresentationRepository(session),
            verification_repo=VerificationRepository(session),
            audit_repo=AuditRepository(session),
            requesting_user=reloaded_user,
        )
        # AO name match → row lands at verified + a Verification event of
        # type `authority_proven` is appended.
        assert new_row.authority_status == "verified"
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
            await handle_create_org_representation(
                payload=payload,
                repo=OrgRepresentationRepository(session),
                verification_repo=VerificationRepository(session),
                audit_repo=AuditRepository(session),
                requesting_user=reloaded_user,
            )


async def test_authorized_official_requires_org_ao_name_cached(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The org's Type-2 NPI must have been verified first so NPPES has
    populated `authorized_official_name`. Without it the AO path can't
    even start."""
    user, org = await _seed_user_and_org(db_test_session_manager)  # no AO name
    await _seed_verified_clinician(
        db_test_session_manager,
        owner_id=user.id,
        first="Jane",
        last="Doe",
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
            await handle_create_org_representation(
                payload=payload,
                repo=OrgRepresentationRepository(session),
                verification_repo=VerificationRepository(session),
                audit_repo=AuditRepository(session),
                requesting_user=reloaded_user,
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
            await handle_create_org_representation(
                payload=payload,
                repo=OrgRepresentationRepository(session),
                verification_repo=VerificationRepository(session),
                audit_repo=AuditRepository(session),
                requesting_user=reloaded_user,
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
            await handle_create_org_representation(
                payload=payload,
                repo=OrgRepresentationRepository(session),
                verification_repo=VerificationRepository(session),
                audit_repo=AuditRepository(session),
                requesting_user=user,
            )


# ---------- rep_approval ------------------------------------------------


async def test_rep_approval_requires_existing_verified_rep_on_org(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The requesting user must already be a verified rep on the target
    org (or be admin). Otherwise the system would let any authed user
    self-approve."""
    user, org = await _seed_user_and_org(db_test_session_manager)
    payload = OrgRepresentationCreate(
        user_id=user.id,
        org_id=org.id,
        role="coordinator",
        authority_method="rep_approval",
    )
    async with db_test_session_manager() as session:
        with pytest.raises(ForbiddenError, match="existing verified representative"):
            await handle_create_org_representation(
                payload=payload,
                repo=OrgRepresentationRepository(session),
                verification_repo=VerificationRepository(session),
                audit_repo=AuditRepository(session),
                requesting_user=user,
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
        new_row = await handle_create_org_representation(
            payload=payload,
            repo=OrgRepresentationRepository(session),
            verification_repo=VerificationRepository(session),
            audit_repo=AuditRepository(session),
            requesting_user=admin,
        )
        assert new_row.authority_status == "verified"


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
        user_id=other.id,  # NOT requesting_user
        org_id=org.id,
        role="coordinator",
        authority_method="admin_review",
    )
    async with db_test_session_manager() as session:
        with pytest.raises(ForbiddenError, match="another user"):
            await handle_create_org_representation(
                payload=payload,
                repo=OrgRepresentationRepository(session),
                verification_repo=VerificationRepository(session),
                audit_repo=AuditRepository(session),
                requesting_user=user,
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
            await handle_create_org_representation(
                payload=payload,
                repo=OrgRepresentationRepository(session),
                verification_repo=VerificationRepository(session),
                audit_repo=AuditRepository(session),
                requesting_user=user,
            )
