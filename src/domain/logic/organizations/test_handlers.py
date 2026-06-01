"""Tests for `Organization` per-spec hook callables.

Pins :func:`organization_form_extras` — the parent-Org picker hook
(issue #581):

* Non-superuser sees only Orgs they own.
* Superuser sees every Org.
* Edit path excludes the row being edited (self-loop prevention).
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.organizations.handlers import organization_form_extras
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.models import Organization, User
from tests.helpers import create_test_user, make_organization_row

pytestmark = pytest.mark.asyncio


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


async def _seed_org(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    owner_id: uuid.UUID,
    name: str,
) -> uuid.UUID:
    org = make_organization_row(owner_id=owner_id, name=name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(org)
    return org.id


# --- organization_form_extras --------------------------------------------


async def test_form_extras_owner_sees_only_owned_orgs(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Create path (target=None): non-superuser sees only Orgs they own."""
    owner = await _seed_user(db_test_session_manager)
    stranger = await _seed_user(db_test_session_manager)
    owned_id = await _seed_org(db_test_session_manager, owner_id=owner.id, name="Mine")
    await _seed_org(db_test_session_manager, owner_id=stranger.id, name="Other")

    async with db_test_session_manager() as session:
        org_repo = OrganizationRepository(session)
        result = await organization_form_extras(
            target=None, requesting_user=owner, organization_repo=org_repo
        )
        ids = [o.id for o in result["parent_org_options"]]
        assert ids == [owned_id]


async def test_form_extras_superuser_sees_all_orgs(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Superuser sees every Org regardless of owner."""
    admin = await _seed_user(db_test_session_manager, is_superuser=True)
    other = await _seed_user(db_test_session_manager)
    await _seed_org(db_test_session_manager, owner_id=admin.id, name="Admin Org")
    await _seed_org(db_test_session_manager, owner_id=other.id, name="Other Org")

    async with db_test_session_manager() as session:
        org_repo = OrganizationRepository(session)
        result = await organization_form_extras(
            target=None, requesting_user=admin, organization_repo=org_repo
        )
        names = {o.name for o in result["parent_org_options"]}
        assert "Admin Org" in names
        assert "Other Org" in names


async def test_form_extras_edit_path_excludes_self(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Edit path: the row being edited is excluded from picker options
    so the form can't pin a self-loop on submit (an Org as its own
    parent)."""
    owner = await _seed_user(db_test_session_manager)
    self_id = await _seed_org(db_test_session_manager, owner_id=owner.id, name="Self")
    sibling_id = await _seed_org(
        db_test_session_manager, owner_id=owner.id, name="Sibling"
    )

    async with db_test_session_manager() as session:
        org_repo = OrganizationRepository(session)
        target = await org_repo.get_by_model_id(Organization, self_id)
        result = await organization_form_extras(
            target=target, requesting_user=owner, organization_repo=org_repo
        )
        ids = {o.id for o in result["parent_org_options"]}
        assert self_id not in ids
        assert sibling_id in ids


# --- Admin verification-state axis ---------------------------------------


async def test_set_org_verification_state_matched_writes_audit_and_event(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Admin flips an org to `matched`. Cache updates, `verified_at`
    is set, a `SET_ORG_VERIFICATION_STATE` audit row lands, and an
    `admin_verify` Verification event is appended."""
    from sqlalchemy import select

    from src.domain.logic.organizations.handlers import (
        handle_set_org_verification_state,
    )
    from src.domain.logic.organizations.schema import (
        OrganizationVerificationStateUpdate,
    )
    from src.domain.logic.verifications.repository import VerificationRepository
    from src.domain.models import Verification
    from src.domain.specs.organization import ORGANIZATION_ENTITY
    from src.framework.audit.core import AuditAction
    from src.framework.audit.log import AuditLog
    from src.framework.audit.repository import AuditRepository

    admin = await _seed_user(db_test_session_manager, is_superuser=True)
    owner = await _seed_user(db_test_session_manager)
    org_id = await _seed_org(db_test_session_manager, owner_id=owner.id, name="Acme")

    async with db_test_session_manager() as session:
        await handle_set_org_verification_state(
            organization_id=org_id,
            payload=OrganizationVerificationStateUpdate(state="matched"),
            repo=OrganizationRepository(session),
            verification_repo=VerificationRepository(session),
            audit_repo=AuditRepository(session),
            requesting_user=admin,
        )

    async with db_test_session_manager() as session:
        loaded = await session.get(Organization, org_id)
        assert loaded.npi_match_status == "matched"
        assert loaded.verified_at is not None

        audit_rows = (
            (
                await session.execute(
                    select(AuditLog).filter(
                        AuditLog.resource_type == ORGANIZATION_ENTITY.audit.type,
                        AuditLog.resource_id == org_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert AuditAction.SET_ORG_VERIFICATION_STATE.value in {
            r.action for r in audit_rows
        }

        events = (
            (
                await session.execute(
                    select(Verification).filter(
                        Verification.org_id == org_id,
                        Verification.event_type == "admin_verify",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1


async def test_set_org_verification_state_mismatch_records_admin_suspend(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    from sqlalchemy import select

    from src.domain.logic.organizations.handlers import (
        handle_set_org_verification_state,
    )
    from src.domain.logic.organizations.schema import (
        OrganizationVerificationStateUpdate,
    )
    from src.domain.logic.verifications.repository import VerificationRepository
    from src.domain.models import Verification
    from src.framework.audit.repository import AuditRepository

    admin = await _seed_user(db_test_session_manager, is_superuser=True)
    owner = await _seed_user(db_test_session_manager)
    org_id = await _seed_org(db_test_session_manager, owner_id=owner.id, name="Acme")

    async with db_test_session_manager() as session:
        await handle_set_org_verification_state(
            organization_id=org_id,
            payload=OrganizationVerificationStateUpdate(state="mismatch"),
            repo=OrganizationRepository(session),
            verification_repo=VerificationRepository(session),
            audit_repo=AuditRepository(session),
            requesting_user=admin,
        )

    async with db_test_session_manager() as session:
        loaded = await session.get(Organization, org_id)
        assert loaded.npi_match_status == "mismatch"
        events = (
            (
                await session.execute(
                    select(Verification).filter(
                        Verification.org_id == org_id,
                        Verification.event_type == "admin_suspend",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1


async def test_set_org_verification_state_pending_clears_verified_at(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    import datetime

    from src.domain.logic.organizations.handlers import (
        handle_set_org_verification_state,
    )
    from src.domain.logic.organizations.schema import (
        OrganizationVerificationStateUpdate,
    )
    from src.domain.logic.verifications.repository import VerificationRepository
    from src.framework.audit.repository import AuditRepository

    admin = await _seed_user(db_test_session_manager, is_superuser=True)
    owner = await _seed_user(db_test_session_manager)
    org_id = await _seed_org(db_test_session_manager, owner_id=owner.id, name="Acme")
    async with db_test_session_manager() as session:
        async with session.begin():
            row = await session.get(Organization, org_id)
            row.npi_match_status = "matched"
            row.verified_at = datetime.datetime.now(datetime.timezone.utc)

    async with db_test_session_manager() as session:
        await handle_set_org_verification_state(
            organization_id=org_id,
            payload=OrganizationVerificationStateUpdate(state="pending"),
            repo=OrganizationRepository(session),
            verification_repo=VerificationRepository(session),
            audit_repo=AuditRepository(session),
            requesting_user=admin,
        )

    async with db_test_session_manager() as session:
        loaded = await session.get(Organization, org_id)
        assert loaded.npi_match_status == "pending"
        assert loaded.verified_at is None


async def test_set_org_verification_state_non_admin_forbidden(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    from src.domain.logic.organizations.handlers import (
        handle_set_org_verification_state,
    )
    from src.domain.logic.organizations.schema import (
        OrganizationVerificationStateUpdate,
    )
    from src.domain.logic.verifications.repository import VerificationRepository
    from src.framework.audit.repository import AuditRepository
    from src.framework.http.exceptions import ForbiddenError

    non_admin = await _seed_user(db_test_session_manager)
    org_id = await _seed_org(
        db_test_session_manager, owner_id=non_admin.id, name="Acme"
    )

    async with db_test_session_manager() as session:
        with pytest.raises(ForbiddenError):
            await handle_set_org_verification_state(
                organization_id=org_id,
                payload=OrganizationVerificationStateUpdate(state="matched"),
                repo=OrganizationRepository(session),
                verification_repo=VerificationRepository(session),
                audit_repo=AuditRepository(session),
                requesting_user=non_admin,
            )


async def test_set_org_verification_state_404_for_missing(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    from src.domain.logic.organizations.handlers import (
        handle_set_org_verification_state,
    )
    from src.domain.logic.organizations.schema import (
        OrganizationVerificationStateUpdate,
    )
    from src.domain.logic.verifications.repository import VerificationRepository
    from src.framework.audit.repository import AuditRepository
    from src.framework.http.exceptions import NotFoundError

    admin = await _seed_user(db_test_session_manager, is_superuser=True)

    async with db_test_session_manager() as session:
        with pytest.raises(NotFoundError):
            await handle_set_org_verification_state(
                organization_id=uuid.uuid4(),
                payload=OrganizationVerificationStateUpdate(state="matched"),
                repo=OrganizationRepository(session),
                verification_repo=VerificationRepository(session),
                audit_repo=AuditRepository(session),
                requesting_user=admin,
            )
