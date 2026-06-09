"""Tests for `Organization` per-spec hook callables."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


# --- after_create_organization_owner_grant -------------------------------


class _RepRepo:
    """Captures the OrgRepresentation passed to `create`."""

    def __init__(self):
        self.created = None

    async def create(self, obj):
        self.created = obj
        obj.id = uuid.uuid4()
        return obj


async def test_org_after_create_runs_npi_verification_and_passes_when_verified(
    monkeypatch,
):
    """Happy path: NPPES returns `verified`, so the owner rep is granted
    and the hook returns normally. The verification runs with
    `commit=False` so the outer create transaction owns the commit."""
    from types import SimpleNamespace

    from src.domain.logic.organizations import handlers as org_handlers

    captured = {}

    async def _fake_verify(*, org_id, actor_id, commit=True, **_):
        captured["org_id"] = org_id
        captured["actor_id"] = actor_id
        captured["commit"] = commit
        return SimpleNamespace(status="verified", flags=[])

    monkeypatch.setattr(
        "src.domain.logic.verifications.handlers.run_org_verification", _fake_verify
    )

    user = SimpleNamespace(id=uuid.uuid4())
    row = SimpleNamespace(id=uuid.uuid4(), npi="1234567890")
    rep_repo = _RepRepo()

    async def _refresh(*_a, **_kw): ...

    org_repo = SimpleNamespace(session=SimpleNamespace(refresh=_refresh))

    await org_handlers.after_create_organization_owner_grant(
        row=row,
        requesting_user=user,
        org_rep_repo=rep_repo,
        verification_repo=None,
        organization_repo=org_repo,
        verification_audit_repo=None,
    )

    assert rep_repo.created is not None
    assert rep_repo.created.role == "owner"
    assert captured["org_id"] == row.id
    assert captured["actor_id"] == user.id
    assert captured["commit"] is False


async def test_org_after_create_raises_when_verification_fails(monkeypatch):
    """NPPES returns a non-verified status → the hook raises
    BadRequestError. The exception carries a user-facing message derived
    from the verification flags; the outer `mutate(...)` block rolls
    back the org + the queued owner-rep grant."""
    from types import SimpleNamespace

    from src.domain.logic.organizations import handlers as org_handlers
    from src.framework.http.exceptions import BadRequestError

    async def _fake_verify(**_):
        return SimpleNamespace(status="failed", flags=["nppes_npi_not_found"])

    monkeypatch.setattr(
        "src.domain.logic.verifications.handlers.run_org_verification", _fake_verify
    )

    user = SimpleNamespace(id=uuid.uuid4())
    row = SimpleNamespace(id=uuid.uuid4(), npi="1234567890")
    rep_repo = _RepRepo()
    org_repo = SimpleNamespace(session=SimpleNamespace(refresh=lambda *_a, **_kw: None))

    with pytest.raises(BadRequestError) as exc_info:
        await org_handlers.after_create_organization_owner_grant(
            row=row,
            requesting_user=user,
            org_rep_repo=rep_repo,
            verification_repo=None,
            organization_repo=org_repo,
            verification_audit_repo=None,
        )
    assert "NPPES" in str(exc_info.value.detail)


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
