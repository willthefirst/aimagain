"""Deterministic RNG helpers for the seed generator.

A single `SeededRandom` is threaded through every generator so a
re-run produces the same dataset row-for-row. The seed is constant
(`SEED`) — change it only when you deliberately want a different
distribution (and accept that screenshots / golden-output tests will
drift).

The helpers are deliberately small. The pattern they encode:

  - `round_robin(values, index)` — guarantees every value in `values`
    appears at least ⌈N/len⌉ times across N rows. The right primitive
    for any CHECK-constrained column where we want **coverage**
    (every enum value present) instead of probability.

  - `weighted_choice(values, weights)` — for distributions that
    should not be uniform (most providers in CA/NY/TX, not 1/51 each).

  - `subset(values, min_size, max_size)` — for JSON list columns
    (`age_groups`, `languages`, `services`, `settings`, `desired_times`,
    `genders`, `in_network_carriers`). Varies cardinality across the
    range so the dataset has rows with 1 item, rows with many, rows
    with all.

  - `nullable(value, p_null)` — for nullable columns. Returns `None`
    with probability `p_null`. The generator defaults `p_null=0.3`;
    bump per-column when the empty-state UI most needs exercise.

  - `nullable_subset(values, min_size, max_size, p_empty)` — JSON
    list columns whose default is `[]`. Occasionally returns `[]` so
    empty-list UIs are exercised.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Sequence, TypeVar

T = TypeVar("T")

# Bumping this changes every row. Pin it; screenshots / coverage
# tests assume stability.
SEED: int = 20260522


class SeededRandom:
    """Thin wrapper around `random.Random(SEED)` exposing the
    domain-shaped helpers above. Holding it as an object (rather than
    using `random.seed(...)` globally) keeps the seed local to seeding
    and avoids cross-test contamination.
    """

    def __init__(self, seed: int = SEED) -> None:
        self._rng = random.Random(seed)

    # --- atomic primitives -------------------------------------------
    def bool(self, p_true: float = 0.5) -> bool:
        return self._rng.random() < p_true

    def int(self, lo: int, hi: int) -> int:
        return self._rng.randint(lo, hi)

    def choice(self, values: Sequence[T]) -> T:
        return self._rng.choice(values)

    def random(self) -> float:
        return self._rng.random()

    # --- distribution shapes -----------------------------------------
    def round_robin(self, values: Sequence[T], index: int) -> T:
        """Deterministic per-index pick. Every value appears at least
        ⌈N/len(values)⌉ times across N rows — the right shape for
        guaranteed enum coverage.
        """
        return values[index % len(values)]

    def weighted_choice(self, values: Sequence[T], weights: Sequence[float]) -> T:
        return self._rng.choices(values, weights=weights, k=1)[0]

    def subset(
        self, values: Sequence[T], min_size: int = 1, max_size: int | None = None
    ) -> list[T]:
        """Random subset of `values` with cardinality uniformly chosen
        in `[min_size, max_size]`. `max_size=None` means len(values)."""
        if max_size is None:
            max_size = len(values)
        size = self._rng.randint(min_size, min(max_size, len(values)))
        return self._rng.sample(list(values), k=size)

    def nullable(self, value: T, p_null: float = 0.3) -> T | None:
        return None if self.bool(p_null) else value

    def nullable_subset(
        self,
        values: Sequence[T],
        min_size: int = 1,
        max_size: int | None = None,
        p_empty: float = 0.15,
    ) -> list[T]:
        """Subset, but occasionally `[]`. The list itself is never
        None — JSON list columns are NOT NULL with `default=list`."""
        if self.bool(p_empty):
            return []
        return self.subset(values, min_size, max_size)

    # --- dates --------------------------------------------------------
    def date_in_range(self, lo: date, hi: date) -> date:
        """Uniform date between `lo` and `hi` inclusive."""
        delta = (hi - lo).days
        return lo + timedelta(days=self._rng.randint(0, delta))

    def date_within_years(self, years_back: int = 0, years_forward: int = 5) -> date:
        today = date.today()
        return self.date_in_range(
            today - timedelta(days=365 * years_back),
            today + timedelta(days=365 * years_forward),
        )

    def datetime_within_days(self, days_back: int) -> datetime:
        """A point in time uniformly within the last `days_back` days."""
        now = datetime.now(timezone.utc)
        offset = self._rng.randint(0, days_back * 24 * 60)  # minute precision
        return now - timedelta(minutes=offset)

    # --- shuffled view -----------------------------------------------
    def shuffled(self, values: Sequence[T]) -> list[T]:
        out = list(values)
        self._rng.shuffle(out)
        return out


def deterministic_uuid(*parts: str | int) -> uuid.UUID:
    """Stable UUID derived from `parts` via BLAKE2b. Same inputs always
    yield the same UUID so rerunning `dev seed` upserts the same row
    instead of inserting a duplicate. Used as the PK for every
    generator-produced row; `session.merge(row)` then handles
    insert-or-update idempotency.
    """
    payload = "|".join(str(p) for p in parts).encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=16).digest()
    return uuid.UUID(bytes=digest)
