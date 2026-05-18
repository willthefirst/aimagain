"""Tests for `src/framework/actor.py`."""

import uuid
from types import SimpleNamespace
from typing import get_type_hints

from src.domain.models import User
from src.framework.actor import Actor


def test_actor_protocol_fields():
    """The Actor protocol surface is exactly `id`, `is_superuser`,
    `username`. Adding a field here means another domain attribute has
    leaked into the framework — surface that on review instead of
    silently widening the contract."""
    assert set(get_type_hints(Actor).keys()) == {"id", "is_superuser", "username"}


def test_user_satisfies_actor_structurally():
    """The concrete domain ``User`` class declares every attribute the
    framework reads via ``Actor``. Static type checkers verify this for
    annotated call sites; this test pins it at runtime so a future
    rename on ``User`` surfaces here, not as an audit-handler crash."""
    user_attrs = set(dir(User))
    for field in get_type_hints(Actor).keys():
        assert field in user_attrs, f"User is missing Actor field: {field}"


def test_simplenamespace_actor_works_with_framework_callers():
    """An ad-hoc actor-shaped object is sufficient for every framework
    consumer that reads the protocol — tests don't need a SQLAlchemy
    User instance to exercise framework code."""
    from src.framework.authz import is_admin, is_owner

    actor = SimpleNamespace(
        id=uuid.uuid4(),
        is_superuser=True,
        username="root",
    )
    assert is_admin(actor) is True
    assert is_owner(SimpleNamespace(owner_id=actor.id), actor) is True
