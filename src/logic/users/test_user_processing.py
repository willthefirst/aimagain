"""Tests for user orchestration handlers.

The user-detail projection is a security claim — `target_view` must omit
`email`, `is_active`, `is_verified` from any viewer who isn't the user
themselves or an admin. The docstring on `handle_get_user_detail` calls
this defense in depth: a forgotten template guard can re-leak; a missing
dict key can't. These tests pin that invariant so the dict shape is the
load-bearing surface, independent of any template.

Self-target guards on `handle_set_user_activation` and `handle_delete_user`
are pinned here too — direct API callers can't bypass the template's
`{% if %}` hide.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from src.api.common.exceptions import ForbiddenError
from src.logic.users.user_processing import (
    handle_delete_user,
    handle_get_user_detail,
    handle_set_user_activation,
)
from src.models import User
from src.repositories.audit_repository import AuditRepository
from src.repositories.providers.provider_repository import ProviderRepository
from src.repositories.users.user_repository import UserRepository
from src.schemas.users.user import UserActivationUpdate
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio


def _fake_request() -> Request:
    return Request({"type": "http", "headers": [], "method": "GET", "path": "/"})


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


# --- Projection invariant on handle_get_user_detail ----------------------


async def test_get_user_detail_excludes_private_fields_from_stranger(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A non-self, non-admin viewer sees only public fields (id, username)."""
    target = await _seed_user(db_test_session_manager)
    stranger = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        context = await handle_get_user_detail(
            request=_fake_request(),
            user_id=target.id,
            repo=UserRepository(session),
            provider_repo=ProviderRepository(session),
            requesting_user=stranger,
        )

    target_view = context["target_user"]
    assert set(target_view.keys()) == {"id", "username"}
    assert "email" not in target_view
    assert "is_active" not in target_view
    assert "is_verified" not in target_view
    assert context["can_view_private"] is False


async def test_get_user_detail_includes_private_fields_for_self(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The user viewing their own page sees private fields."""
    target = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        context = await handle_get_user_detail(
            request=_fake_request(),
            user_id=target.id,
            repo=UserRepository(session),
            provider_repo=ProviderRepository(session),
            requesting_user=target,
        )

    target_view = context["target_user"]
    assert "email" in target_view
    assert "is_active" in target_view
    assert "is_verified" in target_view
    assert context["can_view_private"] is True


async def test_get_user_detail_includes_private_fields_for_admin(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """An admin viewing another user's page sees private fields."""
    target = await _seed_user(db_test_session_manager)
    admin = await _seed_user(db_test_session_manager, is_superuser=True)

    async with db_test_session_manager() as session:
        context = await handle_get_user_detail(
            request=_fake_request(),
            user_id=target.id,
            repo=UserRepository(session),
            provider_repo=ProviderRepository(session),
            requesting_user=admin,
        )

    target_view = context["target_user"]
    assert "email" in target_view
    assert "is_active" in target_view
    assert "is_verified" in target_view
    assert context["can_view_private"] is True


# --- Self-target guards on activation / delete ---------------------------


async def test_set_user_activation_rejects_self_target(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """An admin cannot flip their own activation via this handler — the
    self-guard lives in logic so direct API calls can't bypass the
    template's `{% if %}` hide."""
    admin = await _seed_user(db_test_session_manager, is_superuser=True)

    async with db_test_session_manager() as session:
        with pytest.raises(ForbiddenError):
            await handle_set_user_activation(
                user_id=admin.id,
                payload=UserActivationUpdate(state="deactivated"),
                repo=UserRepository(session),
                audit_repo=AuditRepository(session),
                requesting_user=admin,
            )


async def test_delete_user_rejects_self_target(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """An admin cannot hard-delete themselves via this handler."""
    admin = await _seed_user(db_test_session_manager, is_superuser=True)

    async with db_test_session_manager() as session:
        with pytest.raises(ForbiddenError):
            await handle_delete_user(
                user_id=admin.id,
                repo=UserRepository(session),
                audit_repo=AuditRepository(session),
                requesting_user=admin,
            )
