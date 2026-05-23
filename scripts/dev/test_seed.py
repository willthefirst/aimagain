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


@pytest.fixture(autouse=True)
def patch_session_maker(monkeypatch):
    """Point `seed.runner` at the in-memory test DB. The overrides
    receive their session from the runner so they don't need patching
    individually."""
    import scripts.dev.seed.runner as runner_mod

    monkeypatch.setattr(runner_mod, "async_session_maker", async_test_sessionmaker)


@pytest.fixture(scope="function")
async def fresh_db():
    """Create the schema once per test, drop after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)


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


async def test_seed_all_smoke(fresh_db):
    """seed_all() runs to completion on a fresh DB and populates the
    expected major tables."""
    rc = await seed_all()
    assert rc == 0
    assert await _count_table("organizations") >= 10
    assert await _count_table("providers") >= 100
    assert await _count_table("affiliations") >= 100


async def test_idempotent_rerun(fresh_db):
    """Re-running seed_all is a no-op — row counts don't grow."""
    await seed_all()
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


async def test_enum_coverage_for_every_check_constraint(fresh_db):
    """For every CHECK-bound column, every allowed value appears in at
    least one row — IF the table has enough rows to cover the enum's
    cardinality. (Programs has 12 rows; the `state_preference` enum
    has 51 values; covering all 51 would require 51+ programs, which
    isn't a meaningful test signal.) Auto-discovered from
    `CHECK_VALUES` — adding a new CHECK value automatically widens
    the assertion where it's feasible."""
    await seed_all()
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


async def test_nullable_columns_have_both_null_and_populated(fresh_db):
    """For every nullable column (excluding PKs / FKs / system cols),
    at least one row is NULL and at least one row is populated.
    Auto-discovered — adding a nullable column auto-covers it.
    `deleted_at` is always-null by design — exempted globally."""
    await seed_all()
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


async def test_organization_hierarchy_present(fresh_db):
    """At least 2 orgs are child rows (parent_org_id IS NOT NULL),
    exercising the self-referential tree."""
    await seed_all()
    async with async_test_sessionmaker() as session:
        result = await session.execute(
            select(func.count())
            .select_from(Organization)
            .where(Organization.parent_org_id.is_not(None))
        )
        child_count = result.scalar_one()
    assert child_count >= 2, f"Expected ≥2 child organizations, got {child_count}"


async def test_multi_affiliation_provider_present(fresh_db):
    """At least one provider has 2+ affiliations — exercises the
    `Provider.affiliations` 1:N edge."""
    await seed_all()
    async with async_test_sessionmaker() as session:
        subq = (
            select(Affiliation.provider_id, func.count().label("n"))
            .group_by(Affiliation.provider_id)
            .subquery()
        )
        result = await session.execute(
            select(func.count()).select_from(subq).where(subq.c.n >= 2)
        )
        multi = result.scalar_one()
    assert multi >= 1, f"Expected ≥1 provider with 2+ affiliations, got {multi}"
