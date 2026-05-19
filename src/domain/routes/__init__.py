"""Importing this package mounts every entity route on the
:data:`src.framework.dispatch.registry.entity_registry`.

Each entity route module calls ``register_entity(SPEC)`` at import
time; this ``__init__`` explicitly imports each one so the registry is
populated whenever the package is loaded (notably by :mod:`src.main`
during app startup, and by the conformance suite during testing).

Adding a new entity route file means adding one import line below.
Forgetting it leaves the spec orphaned — the routes don't mount and
the conformance suite reports the entity missing from the registry.

Non-entity routers (auth, fastapi-users-provided routers) are imported
directly by :mod:`src.main` and not registered here — they aren't
``EntitySpec``-shaped.

The `Post` SQLAlchemy supertype is internal-only; the URL layer
exposes each kind via its own resource family
(:mod:`referrals` / :mod:`openings` / :mod:`intakes`). No `/posts`
collection or detail URL exists.
"""

from . import (
    favorites,
    intakes,
    openings,
    organizations,
    programs,
    providers,
    referrals,
    users,
)

__all__ = [
    "favorites",
    "intakes",
    "openings",
    "organizations",
    "programs",
    "providers",
    "referrals",
    "users",
]
