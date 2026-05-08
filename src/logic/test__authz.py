"""Tests for `src/logic/_authz.py`."""

import uuid
from types import SimpleNamespace

import pytest

from src.api.common.exceptions import ForbiddenError
from src.logic._authz import assert_owner_or_admin


def _user(*, is_superuser: bool = False, id_=None):
    return SimpleNamespace(id=id_ or uuid.uuid4(), is_superuser=is_superuser)


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
