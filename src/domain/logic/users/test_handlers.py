"""Tests for user orchestration handlers.

The user-detail projection is a security claim — `target_view` must omit
`email` and `is_active` from any viewer who isn't the user themselves or
an admin. `is_verified` was removed from the response entirely in #696
(no verification flow; always False). These tests pin the dict shape so
the security invariant holds independent of any template.

Self-target guards (delete + activation) are spec-declared and
framework-enforced — pinned in `src/logic/test__generic.py`.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from src.domain.logic.users.repository import UserRepository
from src.domain.models import User
from src.domain.specs.user import USER_ENTITY
from src.framework.dispatch.mounts.detail import handle_detail
from src.framework.http.exceptions import ForbiddenError
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


async def test_get_user_detail_forbids_stranger(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A non-self, non-admin viewer is denied at the handler boundary —
    `USER_ENTITY.detail_authz` raises before the projection runs, so no
    private fields can leak even via an accidentally-removed template
    guard. The detail page is private between users now."""
    target = await _seed_user(db_test_session_manager)
    stranger = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        with pytest.raises(ForbiddenError):
            await handle_detail(
                USER_ENTITY,
                request=_fake_request(),
                target_id=target.id,
                repo=UserRepository(session),
                requesting_user=stranger,
            )


async def test_get_user_detail_includes_private_fields_for_self(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The user viewing their own page sees private fields."""
    target = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        context = await handle_detail(
            USER_ENTITY,
            request=_fake_request(),
            target_id=target.id,
            repo=UserRepository(session),
            requesting_user=target,
        )

    target_view = context["target_user"]
    assert "email" in target_view
    assert "is_active" in target_view
    assert "is_verified" not in target_view  # removed from response in #696
    assert context["can_view_private"] is True


async def test_get_user_detail_includes_private_fields_for_admin(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """An admin viewing another user's page sees private fields."""
    target = await _seed_user(db_test_session_manager)
    admin = await _seed_user(db_test_session_manager, is_superuser=True)

    async with db_test_session_manager() as session:
        context = await handle_detail(
            USER_ENTITY,
            request=_fake_request(),
            target_id=target.id,
            repo=UserRepository(session),
            requesting_user=admin,
        )

    target_view = context["target_user"]
    assert "email" in target_view
    assert "is_active" in target_view
    assert "is_verified" not in target_view  # removed from response in #696
    assert context["can_view_private"] is True


# Self-target guards on `delete` and the `activation` state-axis are
# spec-declared (`USER_ENTITY.delete_forbid_self=True`,
# `state_axis("activation").forbid_self=True`); the framework enforces
# them, so the rejection behavior is pinned in `src/logic/test__generic.py`
# (for `handle_delete`) and the framework-wrapper test for state-axis
# self-guards. No user-level direct-handler tests needed — the handler
# itself no longer has the boilerplate to test.
