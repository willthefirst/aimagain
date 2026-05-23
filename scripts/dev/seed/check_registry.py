"""Per-column CHECK-vocabulary lookup, derived from `metadata`.

Walks every declared SQLAlchemy `CheckConstraint` on every table in the
project's `metadata` and parses out the `<column> IN ('a', 'b', ...)`
clause to recover the allowed-values tuple. The seed generator then
round-robins over that tuple — and the drift lint (`lint_coverage.py`)
asserts every CHECK-constrained column resolves here, so a future
column adding a CHECK whose SQL doesn't match the `IN (...)` shape
fails CI loudly instead of being silently uncovered.

This means: as long as `enums.py::named_check_in` (or any other
helper) keeps producing `IN (...)` SQL, **adding a new CHECK-bound
column requires zero edits in the seed package**. The CHECK is the
single source of truth; the generator reads it.

Non-IN CHECK constraints (e.g. the NPI shape check
`npi GLOB '[0-9][0-9]...'`) are reported as "unresolved" — those
columns fall through to `COLUMN_VOCAB` in `vocab.py`. The lint
tolerates non-IN CHECKs only when the column also has a vocab entry.
"""

from __future__ import annotations

import re
from typing import Final

from sqlalchemy import CheckConstraint

from src.domain.models import metadata

# `column_name IN ('a', 'b', 'c')` — SQLAlchemy renders the SQL via
# `str(constraint.sqltext)`. Single-quote literals, comma-separated,
# trailing whitespace tolerated.
_IN_CLAUSE = re.compile(
    r"""
    ^\s*
    (?P<column>\w+)
    \s+IN\s+
    \(
        (?P<values>.+?)
    \)
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_LITERAL = re.compile(r"'((?:[^']|'')*)'")


def _parse_in_clause(sql: str) -> tuple[str, tuple[str, ...]] | None:
    """Return `(column, values)` if `sql` is an `<col> IN (...)` clause,
    else None. SQL-quote escaping (`''` → `'`) is unwound."""
    m = _IN_CLAUSE.match(sql.strip())
    if not m:
        return None
    raw_values = m.group("values")
    literals = _LITERAL.findall(raw_values)
    if not literals:
        return None
    values = tuple(v.replace("''", "'") for v in literals)
    return m.group("column"), values


def _build_registry() -> dict[tuple[str, str], tuple[str, ...]]:
    """Index every parseable CHECK constraint by (table, column).

    Imports `metadata` from the domain models package so every model
    class is registered before we walk it. The import path is the
    project's standard one (`src.domain.models`) — same import side
    effects the alembic env uses.
    """
    out: dict[tuple[str, str], tuple[str, ...]] = {}
    for table in metadata.tables.values():
        for constraint in table.constraints:
            if not isinstance(constraint, CheckConstraint):
                continue
            sql = str(constraint.sqltext)
            parsed = _parse_in_clause(sql)
            if parsed is None:
                continue
            column, values = parsed
            out[(table.name, column)] = values
    return out


CHECK_VALUES: Final[dict[tuple[str, str], tuple[str, ...]]] = _build_registry()


def check_values_for(table_name: str, column_name: str) -> tuple[str, ...] | None:
    """Return the allowed values for a CHECK-bound column, or None if
    the column isn't CHECK-bound (or the CHECK isn't an `IN (...)`)."""
    return CHECK_VALUES.get((table_name, column_name))


def unresolved_checks() -> list[tuple[str, str]]:
    """List every CheckConstraint in metadata that *isn't* an
    `<col> IN (...)` clause — i.e. won't resolve via `check_values_for`.
    Used by `lint_coverage.py` to surface CHECKs the generator can't
    automatically cover (e.g. the NPI GLOB check). Each entry is
    `(table_name, raw_sql)`."""
    out: list[tuple[str, str]] = []
    for table in metadata.tables.values():
        for constraint in table.constraints:
            if not isinstance(constraint, CheckConstraint):
                continue
            sql = str(constraint.sqltext)
            if _parse_in_clause(sql) is None:
                out.append((table.name, sql))
    return out
