"""Tests for `dependencies.py` — the generated resolver factory.

Verifies that every repository class in `_REPO_TYPES` has a working
resolver registered in `_REPO_TYPE_RESOLVERS`, that the public
`get_<entity>_repository` names map to the generated resolvers, and
that `resolver_for` raises `UnknownRepoTypeError` for an unregistered
class.
"""

import pytest

from src.framework import dependencies as deps
from src.framework.audit_repository import AuditRepository
from src.framework.dependencies import (
    _REPO_TYPE_RESOLVERS,
    _REPO_TYPES,
    UnknownRepoTypeError,
    get_audit_repository,
    get_post_repository,
    get_provider_repository,
    get_user_favorite_repository,
    get_user_repository,
    resolver_for,
)
from src.repositories.favorites.user_favorite_repository import UserFavoriteRepository
from src.repositories.posts.post_repository import PostRepository
from src.repositories.providers.provider_repository import ProviderRepository
from src.repositories.users.user_repository import UserRepository


def test_every_repo_type_has_a_resolver():
    for cls in _REPO_TYPES:
        assert cls in _REPO_TYPE_RESOLVERS


def test_public_names_match_registry():
    """The public `get_<entity>_repository` exports are direct bindings
    to the generated resolvers — same callables, not lookalikes."""
    pairs = [
        (UserRepository, get_user_repository),
        (PostRepository, get_post_repository),
        (AuditRepository, get_audit_repository),
        (ProviderRepository, get_provider_repository),
        (UserFavoriteRepository, get_user_favorite_repository),
    ]
    for cls, public_resolver in pairs:
        assert _REPO_TYPE_RESOLVERS[cls] is public_resolver


def test_resolver_for_returns_registered_resolver():
    assert resolver_for(UserRepository) is _REPO_TYPE_RESOLVERS[UserRepository]


def test_resolver_for_raises_on_unknown_type():
    class _NotARepo:
        pass

    with pytest.raises(UnknownRepoTypeError):
        resolver_for(_NotARepo)


def test_generated_resolver_returns_an_instance():
    """The closure body is `cls(session)`. Pass a sentinel session and
    confirm the resolver builds an instance — proves the type-binding
    closure works (no shared `cls` variable across resolvers)."""
    sentinel_session = object()
    user_repo = get_user_repository(session=sentinel_session)
    assert isinstance(user_repo, UserRepository)
    provider_repo = get_provider_repository(session=sentinel_session)
    assert isinstance(provider_repo, ProviderRepository)


def test_resolver_name_matches_convention():
    """``_resolver.__name__`` should be ``get_<snake_case>_repository`` so
    stack traces stay readable."""
    assert deps.get_user_repository.__name__ == "get_user_repository"
    assert deps.get_user_favorite_repository.__name__ == "get_user_favorite_repository"
