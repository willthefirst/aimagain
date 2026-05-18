"""Tests for `dependencies.py` — the repository DI registry.

The registry is populated by side-effect: framework-owned repositories
register at import time of `dependencies.py` itself; domain repositories
register at import time of their own module. These tests exercise the
registration primitive directly and verify the imported entity resolvers
are wired correctly.
"""

import pytest

from src.domain.logic.favorites.repository import (
    UserFavoriteRepository,
    get_user_favorite_repository,
)
from src.domain.logic.providers.repository import (
    ProviderRepository,
    get_provider_repository,
)
from src.domain.logic.users.repository import UserRepository, get_user_repository
from src.framework.audit.repository import AuditRepository
from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import (
    _REPO_TYPE_RESOLVERS,
    UnknownRepoTypeError,
    get_audit_repository,
    get_base_repository,
    make_repo_resolver,
    register_repository,
    resolver_for,
)

# --- register_repository ----------------------------------------------------


class SampleRepository(BaseRepository):
    pass


def test_register_repository_returns_resolver_and_indexes_by_class():
    resolver = register_repository(SampleRepository)
    assert _REPO_TYPE_RESOLVERS[SampleRepository] is resolver
    assert resolver_for(SampleRepository) is resolver


def test_register_repository_builds_named_resolver():
    """`__name__` follows `get_<snake_case>_repository` so stack traces
    stay readable when FastAPI logs the dep chain."""
    resolver = register_repository(SampleRepository)
    assert resolver.__name__ == "get_sample_repository"


# --- resolver_for -----------------------------------------------------------


def test_resolver_for_returns_registered_resolver():
    assert resolver_for(UserRepository) is _REPO_TYPE_RESOLVERS[UserRepository]


def test_resolver_for_raises_on_unknown_type():
    class _NotARepo:
        pass

    with pytest.raises(UnknownRepoTypeError) as exc_info:
        resolver_for(_NotARepo)
    # The error message names the missing class and tells the caller
    # which function to call — the fix should be obvious from the trace.
    assert "_NotARepo" in str(exc_info.value)
    assert "register_repository" in str(exc_info.value)


# --- framework-owned bootstrap ---------------------------------------------


def test_framework_owned_repositories_are_preregistered():
    """`BaseRepository` and `AuditRepository` live under `framework/` and
    register at the bottom of `dependencies.py`. Without this, the
    dispatch synthesis would error before any domain repo imports."""
    assert BaseRepository in _REPO_TYPE_RESOLVERS
    assert AuditRepository in _REPO_TYPE_RESOLVERS
    assert get_base_repository is _REPO_TYPE_RESOLVERS[BaseRepository]
    assert get_audit_repository is _REPO_TYPE_RESOLVERS[AuditRepository]


# --- domain-side resolvers --------------------------------------------------


def test_domain_resolvers_are_bound_by_their_module():
    """Each domain repo module owns its own `get_<entity>_repository`
    binding (returned by `register_repository`). Spec files import that
    binding, not the framework module."""
    pairs = [
        (UserRepository, get_user_repository),
        (ProviderRepository, get_provider_repository),
        (UserFavoriteRepository, get_user_favorite_repository),
    ]
    for cls, public_resolver in pairs:
        assert _REPO_TYPE_RESOLVERS[cls] is public_resolver


def test_generated_resolver_returns_an_instance():
    """The closure body is `cls(session)`. Pass a sentinel session and
    confirm the resolver builds an instance — proves the type-binding
    closure works (no shared `cls` variable across resolvers)."""
    sentinel_session = object()
    user_repo = get_user_repository(session=sentinel_session)
    assert isinstance(user_repo, UserRepository)
    provider_repo = get_provider_repository(session=sentinel_session)
    assert isinstance(provider_repo, ProviderRepository)


# --- make_repo_resolver -----------------------------------------------------


def test_make_repo_resolver_is_independent_of_registration():
    """The factory is public so callers that want to build a resolver
    without registering can; `register_repository` composes both."""
    resolver = make_repo_resolver(SampleRepository)
    assert resolver.__name__ == "get_sample_repository"
    sentinel_session = object()
    assert isinstance(resolver(session=sentinel_session), SampleRepository)
