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
exposes two families:

  - :mod:`referrals` — kind-locked leaf (`/referrals`,
    `kind='referral'`).
  - :mod:`openings` — subset-supertype listing both availability
    subkinds (`/openings`, `kind ∈ {clinician_opening,
    program_intake}`). The old `/intakes` URL was folded into
    `/openings` (commit history reachable for archaeology).

No `/posts` collection or detail URL exists.
"""

from . import (
    clinicians,
    favorites,
    openings,
    organizations,
    programs,
    referrals,
    users,
)

__all__ = [
    "clinicians",
    "favorites",
    "openings",
    "organizations",
    "programs",
    "referrals",
    "users",
]
