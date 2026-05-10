from typing import Any, Callable

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db_session

from .audit_repository import AuditRepository
from .favorites.user_favorite_repository import UserFavoriteRepository
from .posts.post_repository import PostRepository
from .providers.provider_repository import ProviderRepository
from .users.user_repository import UserRepository


def get_user_repository(
    session: AsyncSession = Depends(get_db_session),
) -> UserRepository:
    """Dependency provider for UserRepository."""
    return UserRepository(session)


def get_post_repository(
    session: AsyncSession = Depends(get_db_session),
) -> PostRepository:
    """Dependency provider for PostRepository."""
    return PostRepository(session)


def get_audit_repository(
    session: AsyncSession = Depends(get_db_session),
) -> AuditRepository:
    """Dependency provider for AuditRepository."""
    return AuditRepository(session)


def get_provider_repository(
    session: AsyncSession = Depends(get_db_session),
) -> ProviderRepository:
    """Dependency provider for ProviderRepository."""
    return ProviderRepository(session)


def get_user_favorite_repository(
    session: AsyncSession = Depends(get_db_session),
) -> UserFavoriteRepository:
    """Dependency provider for UserFavoriteRepository."""
    return UserFavoriteRepository(session)


# Type → resolver registry. The single source of truth for "how do I inject
# a repository of type T into a route?" The mount layer in
# `src/api/common/resource_routes.py` reads this map to synthesize FastAPI
# route signatures from handler type annotations — a handler param typed
# `repo: ProviderRepository` automatically resolves to
# `Depends(get_provider_repository)`, with no separate declaration on the
# mount call. Adding a new repo means adding one entry here, not threading
# the resolver through every mount call site.
#
# Keep this dict and the resolver definitions above in sync: every entry
# here must point at a callable defined in this module. Conversely, a
# resolver that is *not* in this map cannot be auto-injected by the mount
# layer and would need to be passed via a non-registry path (which we
# currently don't have).
_REPO_TYPE_RESOLVERS: dict[type, Callable[..., Any]] = {
    UserRepository: get_user_repository,
    PostRepository: get_post_repository,
    AuditRepository: get_audit_repository,
    ProviderRepository: get_provider_repository,
    UserFavoriteRepository: get_user_favorite_repository,
}


class UnknownRepoTypeError(KeyError):
    """Raised when a handler asks for a repo type that is not in
    `_REPO_TYPE_RESOLVERS`. The error names the type and points at this
    module so the fix is obvious."""


def resolver_for(repo_type: type) -> Callable[..., Any]:
    """Return the FastAPI `Depends`-style resolver for `repo_type`.

    Raises `UnknownRepoTypeError` with a clear message if the type is not
    registered. The mount layer surfaces this at app startup, so a
    forgotten registry entry fails before serving traffic.
    """
    try:
        return _REPO_TYPE_RESOLVERS[repo_type]
    except KeyError:
        raise UnknownRepoTypeError(
            f"No Depends resolver registered for repository type "
            f"{repo_type!r}. Add an entry to `_REPO_TYPE_RESOLVERS` in "
            f"src/repositories/dependencies.py pointing at the matching "
            f"`get_<entity>_repository` function."
        ) from None
