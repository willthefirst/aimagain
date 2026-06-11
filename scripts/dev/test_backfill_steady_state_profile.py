"""Integration test for the #1358 PR-f sub-1 backfill migration
(``f3c128112fa7``).

Tests the SQL-level data motion: insert representative
``opening_details`` / ``intake_details`` rows, run the backfill
upgrade, and assert the matching ``clinician_affiliations`` /
``clinicians`` / ``programs`` rows now carry the right values. This
complements ``dev migrate roundtrip`` (which only checks schema
shape) and the model-level default tests in
``src/domain/models/*/test_*steady_state_profile.py``.

Mirrors the in-process alembic pattern from ``test_migrate.py`` —
drive ``alembic.command`` against a temp sqlite DB rather than
spawning the CLI.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from alembic import command
from alembic.config import Config

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = PROJECT_ROOT / "config" / "alembic.ini"

# The schema-add migration; we upgrade *up to* this one, populate
# opening_details / intake_details, then upgrade one more step to run
# the backfill and observe its effect in isolation.
_SCHEMA_REV = "e3e0a73e9bc5"
_BACKFILL_REV = "f3c128112fa7"


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return cfg


@pytest.fixture
def temp_db(tmp_path, monkeypatch) -> Path:
    db = tmp_path / "backfill.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    return db


def _exec(db: Path, sql: str, **params: object) -> None:
    conn = sqlite3.connect(db)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _query_one(db: Path, sql: str, **params: object) -> tuple:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def _seed_user(db: Path, user_id: str) -> None:
    _exec(
        db,
        """
        INSERT INTO users (
            id, email, hashed_password, is_active, is_superuser,
            is_verified, username, created_at, updated_at
        ) VALUES (
            :id, :email, 'x', 1, 0, 1, :username,
            '2025-01-01 00:00:00', '2025-01-01 00:00:00'
        )
        """,
        id=user_id,
        email=f"{user_id}@example.com",
        username=user_id,
    )


def _seed_clinician(db: Path, clinician_id: str, owner_id: str) -> None:
    _exec(
        db,
        """
        INSERT INTO clinicians (
            id, owner_id, first_name, last_name,
            created_at, updated_at
        ) VALUES (
            :id, :owner_id, 'Jane', 'Smith',
            '2025-01-01 00:00:00', '2025-01-01 00:00:00'
        )
        """,
        id=clinician_id,
        owner_id=owner_id,
    )


def _seed_affiliation(db: Path, aff_id: str, clinician_id: str) -> None:
    _exec(
        db,
        """
        INSERT INTO clinician_affiliations (
            id, clinician_id, accepts_out_of_network,
            in_network_carriers, sliding_scale,
            created_at, updated_at
        ) VALUES (
            :id, :clinician_id, 1, '[]', 0,
            '2025-01-01 00:00:00', '2025-01-01 00:00:00'
        )
        """,
        id=aff_id,
        clinician_id=clinician_id,
    )


def _seed_org(db: Path, org_id: str, owner_id: str) -> None:
    _exec(
        db,
        """
        INSERT INTO organizations (
            id, owner_id, name, created_at, updated_at
        ) VALUES (
            :id, :owner_id, 'Acme', '2025-01-01 00:00:00',
            '2025-01-01 00:00:00'
        )
        """,
        id=org_id,
        owner_id=owner_id,
    )


def _seed_program(db: Path, program_id: str, owner_id: str, org_id: str) -> None:
    _exec(
        db,
        """
        INSERT INTO programs (
            id, owner_id, org_id, name, accepting_referrals,
            created_at, updated_at
        ) VALUES (
            :id, :owner_id, :org_id, 'IOP', 1,
            '2025-01-01 00:00:00', '2025-01-01 00:00:00'
        )
        """,
        id=program_id,
        owner_id=owner_id,
        org_id=org_id,
    )


def _seed_post(db: Path, post_id: str, owner_id: str, kind: str, when: str) -> None:
    _exec(
        db,
        """
        INSERT INTO posts (
            id, owner_id, kind, created_at, updated_at
        ) VALUES (
            :id, :owner_id, :kind, :when, :when
        )
        """,
        id=post_id,
        owner_id=owner_id,
        kind=kind,
        when=when,
    )


def _seed_opening_detail(
    db: Path,
    *,
    post_id: str,
    clinician_id: str,
    affiliation_id: str | None,
    services: str,
    languages: str,
    website: str | None = None,
) -> None:
    _exec(
        db,
        """
        INSERT INTO opening_details (
            post_id, clinician_id, clinician_affiliation_id,
            desired_times, services, settings, modalities,
            age_groups, languages, genders, website
        ) VALUES (
            :post_id, :clinician_id, :aff_id,
            '[]', :services, '[]', '[]',
            '[]', :languages, '[]', :website
        )
        """,
        post_id=post_id,
        clinician_id=clinician_id,
        aff_id=affiliation_id,
        services=services,
        languages=languages,
        website=website,
    )


def _seed_intake_detail(
    db: Path,
    *,
    post_id: str,
    program_id: str,
    services: str,
    languages: str,
) -> None:
    _exec(
        db,
        """
        INSERT INTO intake_details (
            post_id, program_id,
            desired_times, services, settings, modalities,
            age_groups, languages, genders
        ) VALUES (
            :post_id, :program_id,
            '[]', :services, '[]', '[]',
            '[]', :languages, '[]'
        )
        """,
        post_id=post_id,
        program_id=program_id,
        services=services,
        languages=languages,
    )


def test_backfill_copies_opening_detail_into_affiliation_and_clinician(
    temp_db: Path,
):
    """End-to-end: a clinician with one OpeningDetail attached to a
    specific affiliation. After the backfill runs, that affiliation's
    profile columns carry the opening's values, and the clinician's
    ``languages`` carries the opening's languages."""
    cfg = _alembic_config()
    command.upgrade(cfg, _SCHEMA_REV)

    owner_id = str(uuid.uuid4())
    clinician_id = str(uuid.uuid4())
    aff_id = str(uuid.uuid4())
    post_id = str(uuid.uuid4())
    _seed_user(temp_db, owner_id)
    _seed_clinician(temp_db, clinician_id, owner_id)
    _seed_affiliation(temp_db, aff_id, clinician_id)
    _seed_post(temp_db, post_id, owner_id, "clinician_opening", "2025-05-01 00:00:00")
    _seed_opening_detail(
        temp_db,
        post_id=post_id,
        clinician_id=clinician_id,
        affiliation_id=aff_id,
        services='["medication_management"]',
        languages='["en", "es"]',
        website="https://example.com/p",
    )

    # Run the backfill.
    command.upgrade(cfg, _BACKFILL_REV)

    aff_row = _query_one(
        temp_db,
        "SELECT services, website FROM clinician_affiliations WHERE id = :id",
        id=aff_id,
    )
    # The affiliation row gets the opening_detail fields *except*
    # languages — `languages` is NOT a column on
    # `clinician_affiliations` (deliberate per #1358; it lives on
    # `clinicians` as a person attribute).
    assert aff_row[0] == '["medication_management"]'
    assert aff_row[1] == "https://example.com/p"

    clinician_row = _query_one(
        temp_db,
        "SELECT languages FROM clinicians WHERE id = :id",
        id=clinician_id,
    )
    assert clinician_row[0] == '["en", "es"]'


def test_backfill_picks_most_recent_opening_per_affiliation(temp_db: Path):
    """Two OpeningDetails for the same affiliation: the backfill picks
    the most-recent by post ``created_at``. Stale older announcements
    don't overwrite the live state."""
    cfg = _alembic_config()
    command.upgrade(cfg, _SCHEMA_REV)

    owner_id = str(uuid.uuid4())
    clinician_id = str(uuid.uuid4())
    aff_id = str(uuid.uuid4())
    _seed_user(temp_db, owner_id)
    _seed_clinician(temp_db, clinician_id, owner_id)
    _seed_affiliation(temp_db, aff_id, clinician_id)

    older_post = str(uuid.uuid4())
    newer_post = str(uuid.uuid4())
    _seed_post(
        temp_db, older_post, owner_id, "clinician_opening", "2024-01-01 00:00:00"
    )
    _seed_post(
        temp_db, newer_post, owner_id, "clinician_opening", "2025-09-01 00:00:00"
    )
    _seed_opening_detail(
        temp_db,
        post_id=older_post,
        clinician_id=clinician_id,
        affiliation_id=aff_id,
        services='["psychotherapy"]',
        languages='["en"]',
    )
    _seed_opening_detail(
        temp_db,
        post_id=newer_post,
        clinician_id=clinician_id,
        affiliation_id=aff_id,
        services='["medication_management"]',
        languages='["en", "zh"]',
    )

    command.upgrade(cfg, _BACKFILL_REV)

    aff_services = _query_one(
        temp_db,
        "SELECT services FROM clinician_affiliations WHERE id = :id",
        id=aff_id,
    )[0]
    assert aff_services == '["medication_management"]'
    clinician_languages = _query_one(
        temp_db,
        "SELECT languages FROM clinicians WHERE id = :id",
        id=clinician_id,
    )[0]
    assert clinician_languages == '["en", "zh"]'


def test_backfill_handles_clinician_with_single_affiliation_when_id_null(
    temp_db: Path,
):
    """An OpeningDetail whose ``clinician_affiliation_id`` is NULL is
    attributed to the clinician's affiliation only when there is
    exactly one — unambiguous. Multi-affiliation clinicians without
    an explicit FK are skipped to avoid silently picking the wrong
    one."""
    cfg = _alembic_config()
    command.upgrade(cfg, _SCHEMA_REV)

    owner_id = str(uuid.uuid4())
    clinician_id = str(uuid.uuid4())
    aff_id = str(uuid.uuid4())
    _seed_user(temp_db, owner_id)
    _seed_clinician(temp_db, clinician_id, owner_id)
    _seed_affiliation(temp_db, aff_id, clinician_id)

    post_id = str(uuid.uuid4())
    _seed_post(temp_db, post_id, owner_id, "clinician_opening", "2025-01-01 00:00:00")
    _seed_opening_detail(
        temp_db,
        post_id=post_id,
        clinician_id=clinician_id,
        affiliation_id=None,
        services='["psychotherapy"]',
        languages='["en"]',
    )

    command.upgrade(cfg, _BACKFILL_REV)

    aff_services = _query_one(
        temp_db,
        "SELECT services FROM clinician_affiliations WHERE id = :id",
        id=aff_id,
    )[0]
    assert aff_services == '["psychotherapy"]'


def test_backfill_copies_intake_detail_into_program(temp_db: Path):
    """Symmetric to the OpeningDetail test, on the Program side. The
    IntakeDetail's profile columns land on the Program — including
    ``languages``, which on this side lives on the Program (the
    *offering*) rather than on a person."""
    cfg = _alembic_config()
    command.upgrade(cfg, _SCHEMA_REV)

    owner_id = str(uuid.uuid4())
    org_id = str(uuid.uuid4())
    program_id = str(uuid.uuid4())
    _seed_user(temp_db, owner_id)
    _seed_org(temp_db, org_id, owner_id)
    _seed_program(temp_db, program_id, owner_id, org_id)
    post_id = str(uuid.uuid4())
    _seed_post(temp_db, post_id, owner_id, "program_intake", "2025-04-01 00:00:00")
    _seed_intake_detail(
        temp_db,
        post_id=post_id,
        program_id=program_id,
        services='["medication_management", "psychotherapy"]',
        languages='["en", "zh"]',
    )

    command.upgrade(cfg, _BACKFILL_REV)

    row = _query_one(
        temp_db,
        "SELECT services, languages FROM programs WHERE id = :id",
        id=program_id,
    )
    assert row[0] == '["medication_management", "psychotherapy"]'
    assert row[1] == '["en", "zh"]'


def test_backfill_leaves_unattributed_rows_at_defaults(temp_db: Path):
    """An affiliation / program with no opening / intake announcements
    keeps the schema defaults. Backfill is *additive copying*, never
    overwrite-with-NULL."""
    cfg = _alembic_config()
    command.upgrade(cfg, _SCHEMA_REV)

    owner_id = str(uuid.uuid4())
    clinician_id = str(uuid.uuid4())
    aff_id = str(uuid.uuid4())
    _seed_user(temp_db, owner_id)
    _seed_clinician(temp_db, clinician_id, owner_id)
    _seed_affiliation(temp_db, aff_id, clinician_id)

    command.upgrade(cfg, _BACKFILL_REV)

    row = _query_one(
        temp_db,
        "SELECT services, website, currently_accepting_new_patients "
        "FROM clinician_affiliations WHERE id = :id",
        id=aff_id,
    )
    assert row[0] == "[]"
    assert row[1] is None
    assert row[2] == 0


def test_backfill_is_idempotent(temp_db: Path):
    """Running the backfill twice in a row leaves the state unchanged.
    SQLite migrations don't have a "run once" guarantee — the
    deployment flow runs ``alembic upgrade head`` on every container
    start — so the migration must be idempotent against any state it
    has already written.

    Implementation note: running ``alembic upgrade head`` after the
    DB is already at head is itself a no-op (alembic skips applied
    revisions), so we exercise idempotency by running the migration
    function directly against an already-backfilled DB.
    """
    cfg = _alembic_config()
    command.upgrade(cfg, _SCHEMA_REV)

    owner_id = str(uuid.uuid4())
    clinician_id = str(uuid.uuid4())
    aff_id = str(uuid.uuid4())
    _seed_user(temp_db, owner_id)
    _seed_clinician(temp_db, clinician_id, owner_id)
    _seed_affiliation(temp_db, aff_id, clinician_id)
    post_id = str(uuid.uuid4())
    _seed_post(temp_db, post_id, owner_id, "clinician_opening", "2025-01-01 00:00:00")
    _seed_opening_detail(
        temp_db,
        post_id=post_id,
        clinician_id=clinician_id,
        affiliation_id=aff_id,
        services='["medication_management"]',
        languages='["en"]',
    )

    command.upgrade(cfg, _BACKFILL_REV)
    first = _query_one(
        temp_db,
        "SELECT services FROM clinician_affiliations WHERE id = :id",
        id=aff_id,
    )[0]

    # Re-run the migration function in-process. Use SQLAlchemy core
    # so the run mirrors the production engine wiring.
    import importlib.util

    migration_path = (
        PROJECT_ROOT
        / "alembic"
        / "versions"
        / "f3c128112fa7_backfill_steady_state_profile_cols_from_.py"
    )
    spec = importlib.util.spec_from_file_location("_backfill_mig", migration_path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    engine = create_engine(f"sqlite:///{temp_db}")
    try:
        with engine.begin() as conn:
            mod._backfill_affiliations(conn)
            mod._backfill_clinician_languages(conn)
            mod._backfill_programs(conn)
            second = conn.execute(
                text("SELECT services FROM clinician_affiliations WHERE id = :id"),
                {"id": aff_id},
            ).scalar()
    finally:
        engine.dispose()

    assert first == second == '["medication_management"]'
