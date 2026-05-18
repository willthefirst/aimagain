"""Structural type for the auth-resolved requester.

Framework-side handlers and audit helpers only read three fields from
the authenticated principal — ``id`` (for FK writes and self-checks),
``is_superuser`` (admin gate), and ``username`` (chrome scalar). Typing
those parameters as ``Actor`` instead of the concrete domain ``User``
keeps the framework from having to import a domain class.

The concrete ``src.domain.models.User`` satisfies this protocol by
structure — no inheritance, no registration. Tests can hand a
``SimpleNamespace`` or any small stand-in object to the same call sites
without constructing a SQLAlchemy row.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class Actor(Protocol):
    id: UUID
    is_superuser: bool
    username: str
