"""Drift detection for the seed generator. Wired into `dev lint`.

Hard-fails (exit 1) on any of:

  1. A free-text column with no CHECK, no entry in `vocab.COLUMN_VOCAB`,
     and no entry in `vocab.PLACEHOLDER_OK`. The next `dev seed` would
     either crash (`UncoverableColumn`) or — worse — silently leave a
     NULL violation. The lint surfaces it at PR time so the developer
     picks: real vocab entry, or explicit "placeholder is fine"
     allowlist entry.

  2. A non-`IN (...)` CHECK constraint on a column with no
     COLUMN_VOCAB strategy. The generator can't read non-IN CHECKs
     (e.g. the NPI GLOB shape check); they only work because there's
     a hand-written strategy (`npi` in COLUMN_VOCAB). A new such
     check without a matching vocab entry would silently violate the
     CHECK at insert time.

  3. A `JSON` column whose name isn't in `vocab.JSON_LIST_SOURCE` and
     isn't nullable. Generic JSON fallback writes `[]` if the column's
     default is list — but the lint forces the developer to think
     about whether `[]` is meaningful or a typed enum subset is wanted.

The lint walks `metadata.tables` so it sees every declared model.
Adding a new model triggers the lint on the next CI run; the
developer's next move is either a one-line vocab entry, a one-line
PLACEHOLDER_OK entry, or a fresh `overrides/` module.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable

from sqlalchemy import JSON as SAJSON
from sqlalchemy import Boolean, Date, DateTime, Float, Integer, Text
from sqlalchemy.sql.sqltypes import Uuid

from src.domain.models import metadata

from .check_registry import check_values_for, unresolved_checks
from .generators import SYSTEM_COLUMNS
from .vocab import COLUMN_VOCAB, JSON_LIST_SOURCE, PLACEHOLDER_OK

# Columns the framework / fastapi-users owns; not a seed concern.
_FRAMEWORK_COLUMNS: frozenset[str] = frozenset(
    {"id", "hashed_password", "is_active", "is_verified", "is_superuser"}
)


def _column_is_text(column) -> bool:
    try:
        py = column.type.python_type
    except (NotImplementedError, AttributeError):
        return False
    return isinstance(column.type, Text) or py is str


def _column_is_json(column) -> bool:
    return isinstance(column.type, SAJSON)


def _column_is_well_typed_scalar(column) -> bool:
    """Bool / Date / DateTime / Float / Integer / Uuid — the generic
    generator covers these by type, so they need no vocab entry."""
    return isinstance(column.type, (Boolean, Date, DateTime, Float, Integer, Uuid))


def _problems() -> Iterable[str]:
    seen_text_columns: set[tuple[str, str]] = set()

    for table in metadata.tables.values():
        for column in table.columns:
            if column.name in SYSTEM_COLUMNS or column.name in _FRAMEWORK_COLUMNS:
                continue
            if column.primary_key or column.foreign_keys:
                continue

            tname = table.name
            cname = column.name

            # 1) Free-text uncovered.
            if _column_is_text(column):
                covered = (
                    check_values_for(tname, cname) is not None
                    or cname in COLUMN_VOCAB
                    or cname in PLACEHOLDER_OK
                )
                if not covered and (tname, cname) not in seen_text_columns:
                    seen_text_columns.add((tname, cname))
                    yield (
                        f"  ❌ free-text column `{tname}.{cname}` has no CHECK, "
                        f"no COLUMN_VOCAB strategy, and isn't in PLACEHOLDER_OK.\n"
                        f"     → add an entry to scripts/dev/seed/vocab.py::COLUMN_VOCAB "
                        f"or, if a `{cname}_NNN` placeholder is acceptable, list "
                        f"`{cname}` in PLACEHOLDER_OK."
                    )

            # 3) JSON without a known enum source AND non-nullable.
            if _column_is_json(column) and cname not in JSON_LIST_SOURCE:
                if not column.nullable:
                    yield (
                        f"  ❌ non-nullable JSON column `{tname}.{cname}` has no "
                        f"entry in JSON_LIST_SOURCE.\n"
                        f"     → declare its source enum in "
                        f"scripts/dev/seed/vocab.py::JSON_LIST_SOURCE."
                    )

    # 2) Non-IN CHECKs without a COLUMN_VOCAB strategy.
    for tname, sql in unresolved_checks():
        # Try to extract a column name from the SQL — best-effort.
        # If we can't, surface the whole SQL.
        words = sql.split()
        likely_col = next(
            (w for w in words if w.replace("_", "").isalnum() and w.islower()),
            None,
        )
        if likely_col and likely_col in COLUMN_VOCAB:
            continue
        if likely_col and likely_col in PLACEHOLDER_OK:
            continue
        yield (
            f"  ❌ non-IN CHECK on `{tname}` ({sql!r}) has no matching "
            f"COLUMN_VOCAB entry.\n"
            f"     → add a strategy to scripts/dev/seed/vocab.py::COLUMN_VOCAB "
            f"that produces values satisfying this CHECK."
        )


def main() -> int:
    problems = list(_problems())
    if not problems:
        print("✅ scripts/dev/seed coverage: every schema column has a strategy.")
        return 0
    print(
        "❌ scripts/dev/seed coverage drift detected. See "
        "scripts/dev/seed/README.md for how to extend.\n"
    )
    for line in problems:
        print(line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
