"""Introspection-driven row builder.

For any model that has no entry in `overrides.OVERRIDES`, the runner
calls `build_row(model, index, rng, pool)` here. The function walks
`model.__table__.columns` and decides a value for each column from:

  1. `check_registry.CHECK_VALUES` for CHECK-bound columns (round-robin).
  2. `vocab.JSON_LIST_SOURCE` for JSON list columns referencing an enum.
  3. `vocab.COLUMN_VOCAB` for free-text columns with a domain-meaningful
     name (`first_name`, `cost`, `website`, …).
  4. Column type (Boolean → 50/50, Date → uniform window, Integer → small).
  5. FK columns → pick an already-seeded row from `pool`.
  6. Nullable columns → `None` ~30% of the time (50%+ for empty-state
     UI hotspots — see `_NULL_PROBABILITY_BOOST`).
  7. PLACEHOLDER fallback: `<column_name>_<index>` for free-text columns
     whose name is in `PLACEHOLDER_OK`.

If none of the above resolves, raise `UncoverableColumn` — the drift
lint catches this at CI time so an uncovered new column never silently
ships placeholder garbage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON as SAJSON
from sqlalchemy import Boolean, Date, DateTime, Float, Integer, Text
from sqlalchemy.sql.sqltypes import Uuid

from src.framework.persistence.base_model import BaseModel

from .check_registry import check_values_for
from .rng import SeededRandom, deterministic_uuid
from .vocab import (
    COLUMN_VOCAB,
    JSON_LIST_SOURCE,
    PLACEHOLDER_OK,
    _zip_for_state,
)

# Audit timestamps + soft-delete come from `BaseModel`'s mixin columns;
# the generator never sets them — `created_at`/`updated_at` have
# server defaults; `deleted_at` is nullable and stays NULL.
SYSTEM_COLUMNS: frozenset[str] = frozenset({"created_at", "updated_at", "deleted_at"})

# Per-column null-probability overrides. Bumps the default 0.3 for
# fields where the empty-state UI most needs exercise — bigger sample
# of NULLs makes filter combinations / "no value" rendering visible.
_NULL_PROBABILITY_BOOST: dict[str, float] = {
    "cost": 0.6,
    "end_date": 0.5,
    "start_date": 0.4,
    "state_preference": 0.5,
    "npi": 0.4,
    "schedule_text": 0.5,
    "insurance_carrier": 0.4,
    "nppes_result": 0.7,
    "name_match_score": 0.3,
    "expiration_date": 0.3,
    "description": 0.2,
    "referral_instructions": 0.3,
    "website": 0.4,
    "month_completed": 0.2,
}

# JSON-list columns whose default is `[]` → occasionally generate `[]`
# so empty-list UIs are exercised. Per-column override; defaults to
# 0.15 elsewhere.
_EMPTY_LIST_PROBABILITY_BOOST: dict[str, float] = {
    "in_network_carriers": 0.25,
    "genders": 0.20,
    "desired_times": 0.15,
}


class UncoverableColumn(RuntimeError):
    """Raised when `build_row` can't decide a value for a column. The
    drift lint surfaces this at CI time so a new uncovered column
    never silently lands in production."""


@dataclass
class SeedPool:
    """Tracks already-seeded row instances per table for FK resolution.

    `pick(table_name, rng)` returns an arbitrary seeded row; `pick_id`
    is the convenience that returns its `id`. Generators record rows
    they produce via `add` so downstream generators can FK to them.

    Also threads `state_by_index` so the location_state chosen for an
    ClinicianAffiliation gets reused when generating that row's `location_zip`
    (the ZIP prefix is state-dependent).
    """

    _rows_by_table: dict[str, list[Any]] = field(default_factory=dict)
    # Per-row scratch — used by `location_zip` to read the
    # `location_state` already picked for the same row this turn.
    current_state: str | None = None

    def add(self, table_name: str, rows: list[Any]) -> None:
        self._rows_by_table.setdefault(table_name, []).extend(rows)

    def all(self, table_name: str) -> list[Any]:
        return list(self._rows_by_table.get(table_name, []))

    def pick(self, table_name: str, rng: SeededRandom) -> Any:
        rows = self._rows_by_table.get(table_name)
        if not rows:
            raise RuntimeError(
                f"FK target table '{table_name}' has no seeded rows yet — "
                "generation order is wrong (check `metadata.sorted_tables`)."
            )
        return rng.choice(rows)


def _null_probability(column_name: str) -> float:
    return _NULL_PROBABILITY_BOOST.get(column_name, 0.3)


def _empty_list_probability(column_name: str) -> float:
    return _EMPTY_LIST_PROBABILITY_BOOST.get(column_name, 0.15)


def _resolve_fk(column, pool: SeedPool, rng: SeededRandom) -> Any:
    """Pick a target id by following the first foreign key. Multi-FK
    columns are vanishingly rare in this codebase; if one ever appears
    the lint surfaces it."""
    fk = next(iter(column.foreign_keys))
    target_table = fk.column.table.name
    target_row = pool.pick(target_table, rng)
    return target_row.id


def _python_type(column) -> type | None:
    try:
        return column.type.python_type
    except (NotImplementedError, AttributeError):
        return None


def _value_for_column(
    column,
    table_name: str,
    index: int,
    rng: SeededRandom,
    pool: SeedPool,
) -> Any:
    """The single dispatch point for every introspected column.

    Order of strategies is deliberate: FK first (the FK identity is
    the column's job, not the type's); then nullable (a null wins
    over any other strategy); then CHECK (the schema-pinned vocabulary
    trumps name-based heuristics); then JSON list source; then
    name-based COLUMN_VOCAB; then type-based; then placeholder
    fallback for free-text columns in `PLACEHOLDER_OK`.
    """
    name = column.name

    if column.foreign_keys:
        return _resolve_fk(column, pool, rng)

    if column.nullable and rng.bool(_null_probability(name)):
        return None

    check_values = check_values_for(table_name, name)
    if check_values:
        return rng.round_robin(check_values, index)

    # JSON list columns referencing an enum.
    if isinstance(column.type, SAJSON):
        source = JSON_LIST_SOURCE.get(name)
        if source is not None:
            return rng.nullable_subset(
                source,
                min_size=1,
                max_size=min(6, len(source)),
                p_empty=_empty_list_probability(name),
            )
        # JSON column with no declared source: empty list / dict by default
        # is the safest fallback. (`Verification.nppes_result` is the
        # only such column today; its nullability path handled it above.)
        return [] if column.default and column.default.arg is list else {}

    # Name-based strategy (vocab) — first because it's more specific
    # than type-based defaults.
    if name in COLUMN_VOCAB:
        return COLUMN_VOCAB[name](rng, index)

    # State-dependent ZIP: read the state already chosen this turn.
    if name == "location_zip" and pool.current_state is not None:
        return _zip_for_state(rng, pool.current_state)

    # Type-based defaults.
    py = _python_type(column)
    if isinstance(column.type, Boolean) or py is bool:
        # Default-True columns lean true; default-False lean false; else 50/50.
        if column.default is not None and column.default.arg is True:
            return rng.bool(0.7)
        if column.default is not None and column.default.arg is False:
            return rng.bool(0.3)
        return rng.bool(0.5)
    if isinstance(column.type, Date) or py is date:
        return rng.date_within_years(years_back=2, years_forward=5)
    if isinstance(column.type, DateTime) or py is datetime:
        return rng.datetime_within_days(days_back=180)
    if isinstance(column.type, Float) or py is float:
        return round(rng.random(), 3)
    if isinstance(column.type, Integer) or py is int:
        return rng.int(0, 100)
    if isinstance(column.type, Uuid):
        # Non-FK UUID column — rare; deterministic from name+index.
        return deterministic_uuid(table_name, name, index)

    # Free-text fallback.
    if isinstance(column.type, Text) or py is str:
        if name in PLACEHOLDER_OK:
            return f"{name}_{index:03d}"
        raise UncoverableColumn(
            f"Free-text column `{table_name}.{name}` has no CHECK, no entry "
            f"in COLUMN_VOCAB, and isn't in PLACEHOLDER_OK. Add an entry to "
            f"`scripts/dev/seed/vocab.py::COLUMN_VOCAB` (recommended) or list "
            f"the column name in `PLACEHOLDER_OK` if a `{name}_NNN` value is OK."
        )

    raise UncoverableColumn(
        f"Column `{table_name}.{name}` (type={column.type!r}) has no value "
        "strategy. Extend `_value_for_column` in `scripts/dev/seed/generators.py`."
    )


def build_row(
    model: type[BaseModel],
    index: int,
    rng: SeededRandom,
    pool: SeedPool,
) -> BaseModel:
    """Generic introspection-driven row builder.

    Returns a transient instance with a deterministic PK; the runner
    `session.merge`'s it for idempotency. Side rows (hierarchy children)
    are the job of `overrides/`;
    this function only handles "single row, all columns from
    introspection."
    """
    table = model.__table__
    pool.current_state = None
    kwargs: dict[str, Any] = {}

    for column in table.columns:
        if column.name in SYSTEM_COLUMNS:
            continue
        if column.primary_key:
            continue  # set below from deterministic_uuid
        value = _value_for_column(column, table.name, index, rng, pool)
        kwargs[column.name] = value
        # Remember the state pick so the next column (`location_zip`)
        # can read it.
        if column.name == "location_state":
            pool.current_state = value if isinstance(value, str) else None

    # Detail tables (`ReferralDetail`, `OpeningDetail`, `IntakeDetail`)
    # inherit from `Base`, not `BaseModel` — their PK is `post_id`, not
    # `id`. Only set `id` if the model actually has the column.
    if "id" in table.c:
        kwargs["id"] = deterministic_uuid(model.__name__, index)
    return model(**kwargs)
