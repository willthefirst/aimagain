"""FastAPI Depends resolvers for every repository class.

Every repository takes the same constructor — a single ``AsyncSession`` —
so the resolver shape is identical across entities. The factory function
:func:`make_repo_resolver` is the single home for that shape.

Two ways an entity hooks itself in:

* **Domain repositories** call :func:`register_repository` at module load
  (see ``src/domain/logic/<entity>/repository.py``). The call returns the
  generated ``Depends`` provider; the repo module binds it to a
  public ``get_<entity>_repository`` name so spec files can
  ``from src.domain.logic.<entity>.repository import get_<entity>_repository``.
* **Framework-owned repositories** (`BaseRepository`, `AuditRepository`)
  are registered here directly — they live under ``framework/`` and the
  registration call belongs in the same package.

The registry is what the dispatch synthesis reads via
:func:`resolver_for` to inject extra typed repos automatically. Without
registration, the synthesis raises :class:`UnknownRepoTypeError` at app
startup — a forgotten registration never reaches request-handling.
"""

import re
from typing import Any, Callable

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db_session
from src.framework.audit.repository import AuditRepository
from src.framework.persistence.base_repository import BaseRepository

_CAMEL_TO_SNAKE_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _camel_to_snake(name: str) -> str:
    """``UserFavoriteRepository`` → ``user_favorite_repository``."""
    return _CAMEL_TO_SNAKE_RE.sub("_", name).lower()


def make_repo_resolver(cls: type[BaseRepository]) -> Callable[..., Any]:
    """Build a FastAPI ``Depends``-style resolver for `cls`.

    Public so domain repository modules can build their own resolver if
    they prefer to register and bind in two separate steps. Most callers
    use :func:`register_repository` instead, which does both.
    """

    def _resolver(session: AsyncSession = Depends(get_db_session)) -> Any:
        return cls(session)

    stem = _camel_to_snake(cls.__name__.removesuffix("Repository"))
    _resolver.__name__ = f"get_{stem}_repository"
    _resolver.__qualname__ = _resolver.__name__
    return _resolver


# Type → resolver registry consumed by the mount-layer signature
# synthesis (see ``src/framework/dispatch/resource_routes.py``). A handler
# param typed ``repo: ClinicianRepository`` resolves to
# ``Depends(_REPO_TYPE_RESOLVERS[ClinicianRepository])`` automatically.
_REPO_TYPE_RESOLVERS: dict[type, Callable[..., Any]] = {}


def register_repository(cls: type[BaseRepository]) -> Callable[..., Any]:
    """Register `cls` for FastAPI dep injection and return the resolver.

    Called from each ``src/domain/logic/<entity>/repository.py`` after
    the class is declared::

        class ClinicianRepository(BaseRepository):
            ...

        get_clinician_repository = register_repository(ClinicianRepository)

    Spec files then ``from .repository import get_clinician_repository``.
    Returning the resolver lets the caller do register-and-bind in one
    line; the value is also accessible later via :func:`resolver_for`.
    """
    resolver = make_repo_resolver(cls)
    _REPO_TYPE_RESOLVERS[cls] = resolver
    return resolver


# Framework-owned repositories register at module load — they live under
# ``framework/`` so this is the canonical site, not a re-export.
get_base_repository = register_repository(BaseRepository)
get_audit_repository = register_repository(AuditRepository)


class UnknownRepoTypeError(KeyError):
    """Raised when a handler asks for a repo type that is not in
    `_REPO_TYPE_RESOLVERS`. The error names the type and points at
    `register_repository` so the fix is obvious."""


def resolver_for(repo_type: type) -> Callable[..., Any]:
    """Return the FastAPI `Depends`-style resolver for `repo_type`.

    Raises `UnknownRepoTypeError` with a clear message if the type is not
    registered. The mount layer surfaces this at app startup, so a
    forgotten registration fails before serving traffic.
    """
    try:
        return _REPO_TYPE_RESOLVERS[repo_type]
    except KeyError:
        raise UnknownRepoTypeError(
            f"No Depends resolver registered for repository type "
            f"{repo_type!r}. The owning repository module should call "
            f"`register_repository({repo_type.__name__})` after the class "
            f"declaration."
        ) from None
