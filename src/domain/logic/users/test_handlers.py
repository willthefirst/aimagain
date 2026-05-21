"""Tests for user orchestration handlers.

The user-detail projection is a security claim — `target_view` must omit
`email` and `is_active` from any viewer who isn't the user themselves or
an admin. (`is_verified` was dropped from `UserRead` in #696 — the app
has no email-verification flow.) The auto-injected `target_user` projection
on `handle_detail` carries this guarantee from `USER_ENTITY.public_fields`
/ `private_fields` / `private_field_predicate`; the extras callable just
adds the owned-providers list. These tests pin the dict shape so the
security invariant holds independent of any template.

Self-target guards (delete + activation) are spec-declared and
framework-enforced — pinned in `src/logic/test__generic.py`.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from src.domain.logic.providers.repository import ProviderRepository
from src.domain.logic.users.handlers import user_detail_extras
from src.domain.logic.users.repository import UserRepository
from src.domain.models import User
from src.domain.specs.user import USER_ENTITY
from src.framework.dispatch.handlers import handle_detail
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
        context = await handle_detail(
            USER_ENTITY,
            request=_fake_request(),
            target_id=target.id,
            repo=UserRepository(session),
            requesting_user=stranger,
            extras=user_detail_extras,
            extra_kwargs={"provider_repo": ProviderRepository(session)},
        )

    target_view = context["target_user"]
    assert set(target_view.keys()) == {"id", "username"}
    assert "email" not in target_view
    assert "is_active" not in target_view
    assert context["can_view_private"] is False


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
            extras=user_detail_extras,
            extra_kwargs={"provider_repo": ProviderRepository(session)},
        )

    target_view = context["target_user"]
    assert "email" in target_view
    assert "is_active" in target_view
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
            extras=user_detail_extras,
            extra_kwargs={"provider_repo": ProviderRepository(session)},
        )

    target_view = context["target_user"]
    assert "email" in target_view
    assert "is_active" in target_view
    assert context["can_view_private"] is True


# Self-target guards on `delete` and the `activation` state-axis are
# spec-declared (`USER_ENTITY.delete_forbid_self=True`,
# `state_axis("activation").forbid_self=True`); the framework enforces
# them, so the rejection behavior is pinned in `src/logic/test__generic.py`
# (for `handle_delete`) and the framework-wrapper test for state-axis
# self-guards. No user-level direct-handler tests needed — the handler
# itself no longer has the boilerplate to test.
