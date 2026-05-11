"""Tests for `make_entity_router` — the helper that collapses the
APIRouter + BaseRouter scaffolding per route file.

`BaseRouter` itself has implicit coverage via every route test that
goes through a real route; this module isolates the construction
helper.
"""

from types import SimpleNamespace

from fastapi import APIRouter
from pydantic import BaseModel

from src.api.common.base_router import BaseRouter, make_entity_router
from src.api.common.entity_spec import AUTHENTICATED, EntitySpec, RouteSet
from src.logic.audit import AuditAction, AuditedResource, make_snapshotter


class _DummyBody(BaseModel):
    flag: bool


def _audit() -> AuditedResource:
    return AuditedResource(
        type="widget",
        snapshot=make_snapshotter(_DummyBody),
        create=AuditAction.CREATE_USER,
        update=AuditAction.UPDATE_USER,
        delete=AuditAction.DELETE_USER,
    )


def _spec(**overrides) -> EntitySpec:
    defaults = dict(
        name="widget",
        url_collection="widgets",
        id_param="widget_id",
        model=SimpleNamespace,
        audit=_audit(),
        auth_deps=AUTHENTICATED,
        routes=RouteSet(),
    )
    defaults.update(overrides)
    return EntitySpec(**defaults)


def test_default_prefix_derives_from_url_collection():
    """No `prefix_override` → prefix is `/<url_collection>`."""
    router = make_entity_router(_spec())
    assert isinstance(router, BaseRouter)
    assert isinstance(router.router, APIRouter)
    assert router.router.prefix == "/widgets"


def test_default_tags_are_url_collection():
    router = make_entity_router(_spec())
    assert router.default_tags == ["widgets"]


def test_prefix_override_wins_over_default():
    """Favorites' edge entity uses `/users/me/favorites` — the helper
    honors the override and skips the `/url_collection` derivation."""
    router = make_entity_router(_spec(prefix_override="/users/me/favorites"))
    assert router.router.prefix == "/users/me/favorites"


def test_prefix_override_does_not_affect_tags():
    """Tags stay tied to `url_collection` regardless of prefix override;
    the override is purely about URL shape."""
    router = make_entity_router(_spec(prefix_override="/users/me/favorites"))
    assert router.default_tags == ["widgets"]
