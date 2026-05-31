"""Tests for the request-scoped viewer helpers in ``templating.py``."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.framework.rendering.templating import set_viewer, viewer_is_admin


@dataclass
class _User:
    is_superuser: bool


def test_viewer_is_admin_returns_true_for_superuser() -> None:
    set_viewer(_User(is_superuser=True))
    assert viewer_is_admin() is True


def test_viewer_is_admin_returns_false_for_plain_user() -> None:
    set_viewer(_User(is_superuser=False))
    assert viewer_is_admin() is False


def test_viewer_is_admin_returns_false_when_viewer_is_none() -> None:
    set_viewer(None)
    assert viewer_is_admin() is False


@pytest.mark.asyncio
async def test_viewer_is_admin_is_task_scoped() -> None:
    """ContextVar isolation: setting the viewer in one async task does not
    bleed into another task running concurrently."""
    import asyncio

    results: list[bool] = []

    async def task_admin() -> None:
        set_viewer(_User(is_superuser=True))
        await asyncio.sleep(0)
        results.append(viewer_is_admin())

    async def task_plain() -> None:
        set_viewer(_User(is_superuser=False))
        await asyncio.sleep(0)
        results.append(viewer_is_admin())

    await asyncio.gather(task_admin(), task_plain())
    # Each task sees only its own viewer.
    assert True in results
    assert False in results
