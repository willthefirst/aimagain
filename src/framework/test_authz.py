"""Tests for `src/framework/authz.py`."""

import uuid
from types import SimpleNamespace

import pytest

from src.framework.authz import (
    assert_owner_or_admin,
    is_admin,
    is_owner,
    is_owner_or_admin,
    is_self_or_admin,
)
from src.framework.http.exceptions import ForbiddenError


def _user(*, is_superuser: bool = False, id_=None):
    return SimpleNamespace(id=id_ or uuid.uuid4(), is_superuser=is_superuser)


# --- is_admin --------------------------------------------------------------


def test_is_admin_none_user():
    assert is_admin(None) is False


def test_is_admin_regular_user():
    assert is_admin(_user()) is False


def test_is_admin_superuser():
    assert is_admin(_user(is_superuser=True)) is True


# --- is_owner --------------------------------------------------------------


def test_is_owner_none_user():
    obj = SimpleNamespace(owner_id=uuid.uuid4())
    assert is_owner(obj, None) is False


def test_is_owner_matches_owner_id():
    u = _user()
    obj = SimpleNamespace(owner_id=u.id)
    assert is_owner(obj, u) is True


def test_is_owner_non_matching_id():
    u = _user()
    obj = SimpleNamespace(owner_id=uuid.uuid4())
    assert is_owner(obj, u) is False


def test_is_owner_admin_is_not_automatic_owner():
    """`is_owner` checks ownership only; admin-override is the
    `is_owner_or_admin` composition's job, not `is_owner`'s."""
    u = _user(is_superuser=True)
    obj = SimpleNamespace(owner_id=uuid.uuid4())
    assert is_owner(obj, u) is False


def test_is_owner_custom_owner_attr():
    u = _user()
    obj = SimpleNamespace(user_id=u.id)
    assert is_owner(obj, u, owner_attr="user_id") is True


# --- is_owner_or_admin -----------------------------------------------------


def test_is_owner_or_admin_none_user():
    obj = SimpleNamespace(owner_id=uuid.uuid4())
    assert is_owner_or_admin(obj, None) is False


def test_is_owner_or_admin_owner_passes():
    u = _user()
    obj = SimpleNamespace(owner_id=u.id)
    assert is_owner_or_admin(obj, u) is True


def test_is_owner_or_admin_admin_passes_even_if_not_owner():
    admin = _user(is_superuser=True)
    obj = SimpleNamespace(owner_id=uuid.uuid4())
    assert is_owner_or_admin(obj, admin) is True


def test_is_owner_or_admin_stranger_fails():
    u = _user()
    obj = SimpleNamespace(owner_id=uuid.uuid4())
    assert is_owner_or_admin(obj, u) is False


def test_is_owner_or_admin_custom_owner_attr():
    u = _user()
    obj = SimpleNamespace(user_id=u.id)
    assert is_owner_or_admin(obj, u, owner_attr="user_id") is True


# --- is_self_or_admin ------------------------------------------------------


def test_is_self_or_admin_none_actor():
    target = _user()
    assert is_self_or_admin(None, target) is False


def test_is_self_or_admin_self():
    u = _user()
    assert is_self_or_admin(u, u) is True


def test_is_self_or_admin_admin_other():
    admin = _user(is_superuser=True)
    target = _user()
    assert is_self_or_admin(admin, target) is True


def test_is_self_or_admin_stranger():
    actor = _user()
    target = _user()
    assert is_self_or_admin(actor, target) is False


# --- assert_owner_or_admin (composes is_owner + is_admin) ------------------


def test_owner_passes():
    u = _user()
    obj = SimpleNamespace(owner_id=u.id)
    assert_owner_or_admin(obj, u)


def test_superuser_passes_even_if_not_owner():
    u = _user(is_superuser=True)
    obj = SimpleNamespace(owner_id=uuid.uuid4())
    assert_owner_or_admin(obj, u)


def test_non_owner_non_admin_raises():
    u = _user()
    obj = SimpleNamespace(owner_id=uuid.uuid4())
    with pytest.raises(ForbiddenError) as excinfo:
        assert_owner_or_admin(obj, u, action="edit this resource")
    assert "Only the owner or an admin can edit this resource" in str(
        excinfo.value.detail
    )


def test_custom_owner_attr():
    u = _user()
    obj = SimpleNamespace(user_id=u.id)
    assert_owner_or_admin(obj, u, owner_attr="user_id")


def test_custom_action_in_message():
    u = _user()
    obj = SimpleNamespace(owner_id=uuid.uuid4())
    with pytest.raises(ForbiddenError) as excinfo:
        assert_owner_or_admin(obj, u, action="delete this widget")
    assert "delete this widget" in str(excinfo.value.detail)
