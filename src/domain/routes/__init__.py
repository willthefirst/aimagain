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
"""

from . import favorites, organizations, posts, providers, users

__all__ = ["favorites", "organizations", "posts", "providers", "users"]
