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

The `Post` SQLAlchemy supertype is exposed under a single URL family
(`/posts`, whole-supertype face) that lists every kind. The create
form takes `?kind=<value>` and the discriminated-union body adapter
dispatches POST/PATCH bodies by their declared `kind`.
"""

from . import (
    clinicians,
    favorites,
    organizations,
    posts,
    programs,
    users,
)

__all__ = [
    "clinicians",
    "favorites",
    "organizations",
    "posts",
    "programs",
    "users",
]
