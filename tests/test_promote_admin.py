"""Tests for `scripts/dev/promote_admin.py`.

The script flips `is_superuser` on a user matched by email. The admin
bootstrap CLI on prod uses it, so the no-op-on-missing-user and idempotency
guarantees are load-bearing — a typo would silently mint a ghost admin
without them, and re-running the bootstrap should be safe.
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select

from src.models import User
from tests.fixtures import test_async_session_maker as session_maker
from tests.helpers import create_test_user

# Load the script as a module without needing scripts/dev on PYTHONPATH.
_SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "dev" / "promote_admin.py"
)
_spec = importlib.util.spec_from_file_location("promote_admin", _SCRIPT)
promote_admin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(promote_admin)


@pytest.fixture(autouse=True)
def patch_session_maker(monkeypatch):
    """Point the script at the in-memory test database."""
    monkeypatch.setattr(promote_admin, "async_session_maker", session_maker)


async def _insert_user(email: str, is_superuser: bool) -> None:
    async with session_maker() as session:
        async with session.begin():
            session.add(create_test_user(email=email, is_superuser=is_superuser))


async def _is_superuser(email: str) -> bool:
    async with session_maker() as session:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one().is_superuser


async def test_promotes_non_admin_user(db_test_session_manager):
    await _insert_user("alice@example.com", is_superuser=False)

    rc = await promote_admin.set_admin("alice@example.com", revoke=False)

    assert rc == 0
    assert await _is_superuser("alice@example.com") is True


async def test_promote_is_idempotent(db_test_session_manager):
    await _insert_user("alice@example.com", is_superuser=True)

    rc = await promote_admin.set_admin("alice@example.com", revoke=False)

    assert rc == 0
    assert await _is_superuser("alice@example.com") is True


async def test_revokes_admin(db_test_session_manager):
    await _insert_user("alice@example.com", is_superuser=True)

    rc = await promote_admin.set_admin("alice@example.com", revoke=True)

    assert rc == 0
    assert await _is_superuser("alice@example.com") is False


async def test_revoke_is_idempotent(db_test_session_manager):
    await _insert_user("alice@example.com", is_superuser=False)

    rc = await promote_admin.set_admin("alice@example.com", revoke=True)

    assert rc == 0
    assert await _is_superuser("alice@example.com") is False


async def test_missing_user_returns_error(db_test_session_manager, capsys):
    rc = await promote_admin.set_admin("ghost@example.com", revoke=False)

    assert rc == 1
    assert "No user with email ghost@example.com" in capsys.readouterr().err
