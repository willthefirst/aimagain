"""Tests for `_wrap_state_axis_with_self_guard` from `resource_routes.py`.

These tests are colocated with the state_axis mount because the wrapper
is a mount-time concern: it's applied when a ``StateAxis(forbid_self=True)``
axis is mounted onto a route, not inside any per-verb handler.
"""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from src.framework.http.exceptions import ForbiddenError


def _user(*, id_: UUID | None = None, is_superuser: bool = False) -> SimpleNamespace:
    return SimpleNamespace(id=id_ or uuid4(), is_superuser=is_superuser)


# --- StateAxis.forbid_self (mount-time wrapper) --------------------------


@pytest.mark.asyncio
async def test_state_axis_forbid_self_wrapper_rejects_self_target():
    """The `forbid_self` axis flag wraps the resolved handler so a
    self-target invocation raises 403 before the inner handler runs."""
    from src.framework.dispatch.resource_routes import _wrap_state_axis_with_self_guard

    inner_called = False

    async def inner(*, widget_id, requesting_user, payload):
        nonlocal inner_called
        inner_called = True
        return None

    wrapped = _wrap_state_axis_with_self_guard(
        inner, id_param="widget_id", axis_name="activation"
    )
    actor_id = uuid4()
    actor = _user(id_=actor_id)

    with pytest.raises(ForbiddenError, match="activation"):
        await wrapped(widget_id=actor_id, requesting_user=actor, payload=None)
    assert inner_called is False


@pytest.mark.asyncio
async def test_state_axis_forbid_self_wrapper_lets_other_targets_through():
    """The wrapper is a no-op when target_id != requesting_user.id."""
    from src.framework.dispatch.resource_routes import _wrap_state_axis_with_self_guard

    inner_called = False

    async def inner(*, widget_id, requesting_user, payload):
        nonlocal inner_called
        inner_called = True
        return "ok"

    wrapped = _wrap_state_axis_with_self_guard(
        inner, id_param="widget_id", axis_name="activation"
    )

    result = await wrapped(
        widget_id=uuid4(),
        requesting_user=_user(),
        payload=None,
    )
    assert result == "ok"
    assert inner_called is True
