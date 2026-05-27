"""Tests for `scripts/dev/seed/`.

Three things are invariants that future schema changes must not break:

  - **Enum coverage**: every CHECK-constrained column has every allowed
    value present in at least one row. Auto-discovered from
    `check_registry.CHECK_VALUES` — the test doesn't enumerate enums
    by hand, so adding a new enum value automatically widens the
    coverage assertion.

  - **Nullable coverage**: every nullable column has at least one NULL
    row and at least one populated row. Same auto-discovery — adding a
    new nullable column auto-covers it.

  - **Idempotency**: re-running `seed_all` is a no-op (no row counts
    grow). The deterministic-PK + `session.merge` pattern is the
    enforcement; this test pins that the pattern stays effective.

Structural invariants the runtime relies on (hierarchy + multi-affiliation)
also have direct assertions — they're not auto-discoverable from
metadata.

Fixture scope: the schema-create + `seed_all()` runs ONCE per module
(`seeded_db`). Every test in this file is a read-only assertion on the
shared seeded DB except `test_idempotent_rerun`, which re-runs
`seed_all` and asserts row counts haven't grown — re-seeding is a
no-op by contract, so it doesn't perturb the shared state for
subsequent tests. Running seed_all() once instead of per-test cuts
this module from ~38s to ~6s.
"""

from __future__ import annotations

import pytest
from sqlalchemy import JSON as SAJSON
from sqlalchemy import func, select

from scripts.dev.seed import seed_all
from scripts.dev.seed.check_registry import CHECK_VALUES
from src.domain.models import (
    Affiliation,
    Organization,
    metadata,
)
from tests.fixtures import async_test_sessionmaker, test_engine


@pytest.fixture(scope="module")
async def seeded_db():
    """Create the schema and run `seed_all()` once per module. All
    tests in this file are read-only assertions on the shared seeded
    DB except `test_idempotent_rerun`, which exercises re-seeding (a
    no-op by contract).

    Uses `pytest.MonkeyPatch()` directly because the default
    `monkeypatch` fixture is function-scoped; the seed runner's
    `async_session_maker` reference must stay pointed at the test
    sessionmaker for the whole module's seed + assertion run."""
    mp = pytest.MonkeyPatch()
    import scripts.dev.seed.runner as runner_mod

    mp.setattr(runner_mod, "async_session_maker", async_test_sessionmaker)
    async with test_engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)
        await conn.run_sync(metadata.create_all)
    rc = await seed_all()
    assert rc == 0, f"seed_all() failed during module setup (rc={rc})"
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)
    mp.undo()


async def _count_table(table_name: str) -> int:
    async with async_test_sessionmaker() as session:
        result = await session.execute(
            select(func.count()).select_from(metadata.tables[table_name])
        )
        return result.scalar_one()


async def _distinct_values(table_name: str, column_name: str) -> set:
    async with async_test_sessionmaker() as session:
        result = await session.execute(
            select(metadata.tables[table_name].c[column_name]).distinct()
        )
        return {r[0] for r in result.all()}


async def _count_nulls(table_name: str, column_name: str) -> tuple[int, int]:
    col = metadata.tables[table_name].c[column_name]
    async with async_test_sessionmaker() as session:
        nulls = await session.execute(
            select(func.count()).select_from(col.table).where(col.is_(None))
        )
        nonnull = await session.execute(
            select(func.count()).select_from(col.table).where(col.is_not(None))
        )
        return nulls.scalar_one(), nonnull.scalar_one()


async def test_seed_all_smoke(seeded_db):
    """The shared module seed populated the expected major tables."""
    assert await _count_table("organizations") >= 10
    assert await _count_table("clinicians") >= 100
    assert await _count_table("affiliations") >= 100


async def test_idempotent_rerun(seeded_db):
    """Re-running seed_all is a no-op — row counts don't grow. The
    module fixture has already seeded once; this test runs a second
    seed_all and asserts the row counts before/after are equal. The
    no-op property is what lets the shared `seeded_db` fixture work
    safely across tests in this module."""
    counts_first = {
        table.name: await _count_table(table.name)
        for table in metadata.sorted_tables
        if table.name != "audit_log"
    }
    await seed_all()
    counts_second = {
        table.name: await _count_table(table.name)
        for table in metadata.sorted_tables
        if table.name != "audit_log"
    }
    assert counts_first == counts_second


async def test_enum_coverage_for_every_check_constraint(seeded_db):
    """For every CHECK-bound column, every allowed value appears in at
    least one row — IF the table has enough rows to cover the enum's
    cardinality. (Programs has 12 rows; the `state_preference` enum
    has 51 values; covering all 51 would require 51+ programs, which
    isn't a meaningful test signal.) Auto-discovered from
    `CHECK_VALUES` — adding a new CHECK value automatically widens
    the assertion where it's feasible."""
    misses: list[str] = []
    for (table_name, column_name), allowed in CHECK_VALUES.items():
        if table_name not in metadata.tables:
            continue
        row_count = await _count_table(table_name)
        if row_count < len(allowed):
            continue
        actual = await _distinct_values(table_name, column_name)
        actual.discard(None)
        missing = set(allowed) - actual
        if missing:
            misses.append(
                f"  {table_name}.{column_name}: missing {sorted(missing)}; "
                f"present {sorted(actual)}"
            )
    assert not misses, "Enum coverage gaps:\n" + "\n".join(misses)


async def test_nullable_columns_have_both_null_and_populated(seeded_db):
    """For every nullable column (excluding PKs / FKs / system cols),
    at least one row is NULL and at least one row is populated.
    Auto-discovered — adding a nullable column auto-covers it.
    `deleted_at` is always-null by design — exempted globally."""
    system = {"id", "created_at", "updated_at", "deleted_at"}
    misses: list[str] = []
    for table in metadata.tables.values():
        if table.name == "audit_log":
            continue
        if await _count_table(table.name) == 0:
            continue
        for column in table.columns:
            if not column.nullable:
                continue
            if column.name in system or column.primary_key or column.foreign_keys:
                continue
            # JSON columns: SQLAlchemy's default for `None` is to write
            # the JSON null literal (the string `"null"`), not SQL NULL.
            # So `WHERE col IS NULL` is the wrong predicate for these —
            # exempt them; the lint/schema layer is the right home for
            # JSON nullability invariants if they ever matter.
            if isinstance(column.type, SAJSON):
                continue
            null_count, populated = await _count_nulls(table.name, column.name)
            if null_count == 0:
                misses.append(
                    f"  {table.name}.{column.name}: no NULL rows "
                    f"(populated={populated})"
                )
            elif populated == 0:
                misses.append(f"  {table.name}.{column.name}: every row is NULL")
    assert not misses, "Nullable-coverage gaps:\n" + "\n".join(misses)


async def test_organization_hierarchy_present(seeded_db):
    """At least 2 orgs are child rows (parent_org_id IS NOT NULL),
    exercising the self-referential tree."""
    async with async_test_sessionmaker() as session:
        result = await session.execute(
            select(func.count())
            .select_from(Organization)
            .where(Organization.parent_org_id.is_not(None))
        )
        child_count = result.scalar_one()
    assert child_count >= 2, f"Expected ≥2 child organizations, got {child_count}"


async def test_multi_affiliation_clinician_present(seeded_db):
    """At least one clinician has 2+ affiliations — exercises the
    `Clinician.affiliations` 1:N edge."""
    async with async_test_sessionmaker() as session:
        subq = (
            select(Affiliation.clinician_id, func.count().label("n"))
            .group_by(Affiliation.clinician_id)
            .subquery()
        )
        result = await session.execute(
            select(func.count()).select_from(subq).where(subq.c.n >= 2)
        )
        multi = result.scalar_one()
    assert multi >= 1, f"Expected ≥1 clinician with 2+ affiliations, got {multi}"
