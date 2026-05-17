"""FastAPI Depends resolvers for every repository class.

Each repository takes the same constructor — a single ``AsyncSession`` —
so the resolver shape is identical across entities. The resolvers are
built once via :func:`_make_repo_resolver` rather than written by hand;
adding a new repository class is a single entry in :data:`_REPO_TYPES`.

The public ``get_<entity>_repository`` names exist as module-level
bindings so spec files (``src/domain/specs/<entity>.py``) keep
importing them directly. The type → resolver registry is built from
the same source, so a generated resolver and its registry entry can't
drift.
"""

import re
from typing import Any, Callable

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db_session
from src.domain.logic.favorites.repository import UserFavoriteRepository
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.posts.repository import PostRepository
from src.domain.logic.providers.repository import ProviderRepository
from src.domain.logic.users.repository import UserRepository
from src.framework.audit.repository import AuditRepository

from .base_repository import BaseRepository

_CAMEL_TO_SNAKE_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _camel_to_snake(name: str) -> str:
    """``UserFavoriteRepository`` → ``user_favorite_repository``."""
    return _CAMEL_TO_SNAKE_RE.sub("_", name).lower()


def _make_repo_resolver(cls: type[BaseRepository]) -> Callable[..., Any]:
    """Build a FastAPI ``Depends``-style resolver for `cls`.

    Every repository's constructor is ``cls(session: AsyncSession)``, so
    the resolver body is identical — wrap that single call in a closure
    that FastAPI's dep system can `Depends(...)`.
    """

    def _resolver(session: AsyncSession = Depends(get_db_session)) -> Any:
        return cls(session)

    stem = _camel_to_snake(cls.__name__.removesuffix("Repository"))
    _resolver.__name__ = f"get_{stem}_repository"
    _resolver.__qualname__ = _resolver.__name__
    return _resolver


# Single source of truth for "which repository classes participate in
# dep injection." Adding a new repo class means one entry here plus the
# matching public-name binding below; the registry stays in sync because
# it is built from this tuple.
_REPO_TYPES: tuple[type[BaseRepository], ...] = (
    UserRepository,
    BaseRepository,
    AuditRepository,
    ProviderRepository,
    UserFavoriteRepository,
    PostRepository,
    OrganizationRepository,
)


# Type → resolver registry consumed by the mount-layer signature
# synthesis (see ``src/framework/dispatch/resource_routes.py``). A handler param
# typed ``repo: ProviderRepository`` resolves to
# ``Depends(_REPO_TYPE_RESOLVERS[ProviderRepository])`` automatically.
_REPO_TYPE_RESOLVERS: dict[type, Callable[..., Any]] = {
    cls: _make_repo_resolver(cls) for cls in _REPO_TYPES
}


# Public symbols — direct bindings to the generated resolvers so spec
# files can ``from src.framework.persistence.dependencies import get_X_repository``
# the same way they always have.
get_user_repository = _REPO_TYPE_RESOLVERS[UserRepository]
get_base_repository = _REPO_TYPE_RESOLVERS[BaseRepository]
get_audit_repository = _REPO_TYPE_RESOLVERS[AuditRepository]
get_provider_repository = _REPO_TYPE_RESOLVERS[ProviderRepository]
get_user_favorite_repository = _REPO_TYPE_RESOLVERS[UserFavoriteRepository]
get_post_repository = _REPO_TYPE_RESOLVERS[PostRepository]
get_organization_repository = _REPO_TYPE_RESOLVERS[OrganizationRepository]


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
            f"{repo_type!r}. Add an entry to `_REPO_TYPES` in "
            f"src/framework/persistence/dependencies.py."
        ) from None
