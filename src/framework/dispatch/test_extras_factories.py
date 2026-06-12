"""Tests for `src/framework/dispatch/extras_factories.py`."""

from types import SimpleNamespace

import pytest

from src.framework.dispatch.extras_factories import make_detail_extras_handler


@pytest.mark.asyncio
async def test_make_detail_extras_handler_single_fetch():
    """One fetch → one key in the result dict, populated by the
    fetch's awaited return value."""

    async def _fetch(repo, target, requesting_user):
        return repo.suffix + str(target.id)

    hook = make_detail_extras_handler(
        (("label", "main_repo", _fetch),),
    )
    repo = SimpleNamespace(suffix="row-")
    target = SimpleNamespace(id=7)
    result = await hook(target=target, requesting_user=None, main_repo=repo)
    assert result == {"label": "row-7"}


@pytest.mark.asyncio
async def test_make_detail_extras_handler_multiple_fetches_resolve_independently():
    """Multiple fetches assemble into a single dict, each pulling from
    its own declared repo kwarg."""

    async def _fetch_a(repo, _target, _user):
        return repo.value

    async def _fetch_b(repo, _target, _user):
        return repo.value

    hook = make_detail_extras_handler(
        (
            ("a", "repo_a", _fetch_a),
            ("b", "repo_b", _fetch_b),
        ),
    )
    result = await hook(
        target=SimpleNamespace(id=1),
        requesting_user=None,
        repo_a=SimpleNamespace(value="alpha"),
        repo_b=SimpleNamespace(value="beta"),
    )
    assert result == {"a": "alpha", "b": "beta"}


@pytest.mark.asyncio
async def test_make_detail_extras_handler_passes_requesting_user_to_fetch():
    """The viewer is threaded through every fetch — supports per-viewer
    derivations like `is_favorited` without changing the factory shape."""
    seen = {}

    async def _fetch(_repo, _target, requesting_user):
        seen["user"] = requesting_user
        return None

    hook = make_detail_extras_handler((("v", "r", _fetch),))
    user = SimpleNamespace(id="u-1")
    await hook(target=SimpleNamespace(id=1), requesting_user=user, r=None)
    assert seen["user"] is user


@pytest.mark.asyncio
async def test_make_detail_extras_handler_empty_fetches_returns_empty_dict():
    """Zero fetches is a degenerate but valid spec — the hook returns
    `{}` so a future entity can declare the hook target before wiring
    up its first fetch."""
    hook = make_detail_extras_handler(())
    result = await hook(target=SimpleNamespace(id=1), requesting_user=None)
    assert result == {}
