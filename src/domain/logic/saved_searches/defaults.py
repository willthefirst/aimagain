"""The saved searches every user starts with, and the seeding helper.

Each new user begins with two saved searches — the post directory
filtered to openings and to referrals — so the feature is non-empty on
day one. The same `DEFAULT_SAVED_SEARCHES` tuple is the single source
of truth for both seed paths:

  - **Registration** — `seed_default_saved_searches` runs from
    `UserManager.on_after_register` for every new account.
  - **Dev seed** — `scripts/dev/seed/overrides/saved_searches.py` gives
    each seeded user the same two rows.

The filter `kind` values are `POST_KINDS` discriminator keys; the
colocated test pins them against `POST_KINDS.names` so a kind rename
fails loudly here rather than silently producing a dead default.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.models import SavedSearch

# (name, filters) for each default. Names are the user-visible labels;
# filters are `filter_values` dicts (see the model README). Ordered:
# Openings first, Referrals second.
DEFAULT_SAVED_SEARCHES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("Openings", {"kind": "clinician_opening"}),
    ("Referrals", {"kind": "referral"}),
)


async def seed_default_saved_searches(session: AsyncSession, user_id: UUID) -> None:
    """Create the default saved searches for ``user_id`` if absent.

    Takes the caller's session rather than opening its own — the
    registration hook passes the request session that already holds the
    just-committed user, so the seed lands in the same transaction/DB
    the rest of the request uses (and the same DB tests override to).
    Idempotent: skips any default whose name the user already has, so a
    re-run or double-fire can't trip the ``(user_id, name)`` UNIQUE.
    """
    existing = set(
        (
            await session.execute(
                select(SavedSearch.name).where(SavedSearch.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    added = False
    for name, filters in DEFAULT_SAVED_SEARCHES:
        if name in existing:
            continue
        session.add(SavedSearch(user_id=user_id, name=name, filters=dict(filters)))
        added = True
    if added:
        await session.commit()
