"""Tests for `src/framework/rendering/projections.py`."""

from types import SimpleNamespace

import pytest

from src.framework.rendering.projections import project_view


def test_project_view_no_private_fields_returns_only_public():
    obj = SimpleNamespace(id=1, name="w", secret="hidden")
    view = project_view(obj, public_fields=("id", "name"), actor=None)
    assert view == {"id": 1, "name": "w"}


def test_project_view_predicate_false_omits_private():
    obj = SimpleNamespace(id=1, name="w", secret="hidden")
    view = project_view(
        obj,
        public_fields=("id", "name"),
        actor=None,
        private_fields=("secret",),
        private_field_predicate=lambda actor, target: False,
    )
    assert view == {"id": 1, "name": "w"}
    assert "secret" not in view


def test_project_view_predicate_true_includes_private():
    obj = SimpleNamespace(id=1, name="w", secret="hidden")
    view = project_view(
        obj,
        public_fields=("id", "name"),
        actor=None,
        private_fields=("secret",),
        private_field_predicate=lambda actor, target: True,
    )
    assert view == {"id": 1, "name": "w", "secret": "hidden"}


def test_project_view_predicate_receives_actor_and_target():
    """The predicate gets (actor, target) so callers can implement
    self-or-admin, owner-or-admin, etc. without re-deriving inputs."""
    received: dict = {}

    def predicate(actor, target):
        received["actor"] = actor
        received["target"] = target
        return True

    obj = SimpleNamespace(id=1, secret="hidden")
    sentinel_actor = SimpleNamespace(name="actor")
    project_view(
        obj,
        public_fields=("id",),
        actor=sentinel_actor,
        private_fields=("secret",),
        private_field_predicate=predicate,
    )
    assert received["actor"] is sentinel_actor
    assert received["target"] is obj


def test_project_view_different_public_fields_per_view():
    """Same private rule, different call sites can ask for different
    public shapes (e.g. a list row vs. a detail page)."""
    obj = SimpleNamespace(id=1, name="w", description="d", secret="hidden")
    kwargs = dict(
        actor=None,
        private_fields=("secret",),
        private_field_predicate=lambda actor, target: True,
    )
    list_view = project_view(obj, public_fields=("id", "name"), **kwargs)
    detail_view = project_view(
        obj, public_fields=("id", "name", "description"), **kwargs
    )
    assert set(list_view.keys()) == {"id", "name", "secret"}
    assert set(detail_view.keys()) == {"id", "name", "description", "secret"}


def test_project_view_private_fields_without_predicate_raises():
    """Declaring private_fields without a predicate would silently leak
    them — match the spec-level construction guard."""
    obj = SimpleNamespace(id=1, secret="hidden")
    with pytest.raises(ValueError, match="private_field_predicate"):
        project_view(
            obj,
            public_fields=("id",),
            actor=None,
            private_fields=("secret",),
            # private_field_predicate intentionally omitted
        )
