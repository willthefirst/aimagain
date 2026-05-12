"""Guardrail: every FK column has a covering ``relationship()`` at one
end, or appears in ``ALLOWED_BARE_FKS`` with a justification.

Why: SQLAlchemy's flush-ordering graph is built from ``relationship()``
declarations, not raw FK columns. A bare FK lets the unit-of-work flush
child before parent in a single ``session.begin()`` block, which SQLite
(``PRAGMA foreign_keys = ON`` in ``tests/fixtures.py``) rejects with
``FOREIGN KEY constraint failed``. See issue #151 for the originating
incident.
"""

from src.domain.models import Base

# FK columns intentionally left without a relationship. Add new entries
# only with a one-line justification — bare FKs are the exception, not
# the default. Key: ``(table_name, column_name)``. Value: reason.
ALLOWED_BARE_FKS: dict[tuple[str, str], str] = {
    ("audit_log", "actor_id"): (
        "Denormalized historical reference. SET NULL on user delete "
        "means the row is allowed to dangle; audit rows are never "
        "navigated via .actor in code."
    ),
}


def test_every_fk_has_covering_relationship_or_allowlist():
    """Every FK column on a mapped class must either be reachable via a
    ``relationship()`` at one of its two ends, or appear in
    ``ALLOWED_BARE_FKS``. Without one of those, single-transaction seeds
    of (parent, child) can flush in the wrong order and trip FK
    enforcement at runtime."""
    relationship_edges: set[frozenset] = set()
    for mapper in Base.registry.mappers:
        for rel in mapper.relationships:
            relationship_edges.add(frozenset({mapper, rel.mapper}))

    mapper_by_table = {m.local_table: m for m in Base.registry.mappers}

    violations: list[str] = []
    for mapper in Base.registry.mappers:
        table = mapper.local_table
        for column in table.columns:
            for fk in column.foreign_keys:
                if (table.name, column.name) in ALLOWED_BARE_FKS:
                    continue

                referenced_mapper = mapper_by_table.get(fk.column.table)
                if referenced_mapper is None:
                    continue

                if frozenset({mapper, referenced_mapper}) in relationship_edges:
                    continue

                violations.append(
                    f"{table.name}.{column.name} -> {fk.column.table.name} "
                    f"has no covering relationship; add one to either side, "
                    f"or add it to ALLOWED_BARE_FKS with a justification."
                )

    assert not violations, "\n" + "\n".join(violations)
