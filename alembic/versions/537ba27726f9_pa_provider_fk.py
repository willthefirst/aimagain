"""pa_provider_fk

Revision ID: 537ba27726f9
Revises: 5cecf02ed65d
Create Date: 2026-05-12 16:35:00.000000

#448: provider_availability_details points at a Provider profile via
`provider_id` instead of duplicating practice_name + location +
delivery-format columns. Six columns drop off PA; one FK takes their
place.

Backfill for any existing PA rows: find-or-create a Provider for the
PA's owner matching the row's `practice_name`, then point at it. Match
is on `(owner_id, practice_name)` — duplicates within the same owner
collapse to one Provider; missing locations get filled from the PA row
on the create path. After backfill, NOT NULL is asserted on
`provider_id`, then the six redundant columns drop.

Downgrade re-adds the six columns from the linked Provider's data,
then drops `provider_id`. Lossy on session-format mismatches between
the Provider's posture and the PA row's prior values (those values are
gone; we restore from Provider).

**Idempotency note**: SQLite DDL is non-transactional, so a previous
partial run can leave the table in a half-applied state (e.g. column
added but constraints/drops not yet executed). Each step below
inspects the live schema and skips operations that have already been
applied — both upgrade and downgrade are safe to re-run from any
partial state without manual cleanup.

"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "537ba27726f9"
down_revision: Union[str, None] = "5cecf02ed65d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "provider_availability_details"
_OLD_COLUMNS = (
    "practice_name",
    "location_city",
    "location_state",
    "location_zip",
    "in_person_sessions",
    "virtual_sessions",
)
_OLD_CHECK_CONSTRAINTS = (
    "ck_provider_availability_details_location_state",
    "ck_provider_availability_details_in_person_sessions",
    "ck_provider_availability_details_virtual_sessions",
)


def _column_names(bind, table_name):
    return {c["name"] for c in sa.inspect(bind).get_columns(table_name)}


def _check_constraint_names(bind, table_name):
    return {c["name"] for c in sa.inspect(bind).get_check_constraints(table_name)}


def _foreign_key_columns(bind, table_name):
    return {
        tuple(fk["constrained_columns"])
        for fk in sa.inspect(bind).get_foreign_keys(table_name)
    }


def upgrade() -> None:
    bind = op.get_bind()
    existing_cols = _column_names(bind, _TABLE)

    # 1) Add provider_id as nullable so the table stays valid through
    # the backfill. Skip if a prior partial run already added it.
    if "provider_id" not in existing_cols:
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.add_column(sa.Column("provider_id", sa.Uuid(), nullable=True))

    # Re-read column state so the backfill below knows what's still on
    # the table (a partial run may have already dropped the old columns).
    existing_cols = _column_names(bind, _TABLE)
    has_old_columns = all(c in existing_cols for c in _OLD_COLUMNS)

    # 2) Backfill — for each PA row missing a provider_id, find or
    # create a Provider for its owner with matching practice_name and
    # point at it. Idempotent: only NULL provider_id rows are touched,
    # and the find branch is preferred over create so existing
    # Providers are reused.
    if has_old_columns:
        rows = bind.execute(sa.text("""
                SELECT pad.post_id,
                       p.owner_id,
                       pad.practice_name,
                       pad.location_city,
                       pad.location_state,
                       pad.location_zip,
                       pad.in_person_sessions,
                       pad.virtual_sessions
                FROM provider_availability_details AS pad
                JOIN posts AS p ON p.id = pad.post_id
                WHERE pad.provider_id IS NULL
                """)).fetchall()

        for row in rows:
            existing = bind.execute(
                sa.text("""
                    SELECT id FROM providers
                    WHERE owner_id = :owner_id AND practice_name = :practice_name
                    LIMIT 1
                    """),
                {"owner_id": row.owner_id, "practice_name": row.practice_name},
            ).fetchone()
            if existing:
                provider_id = existing.id
            else:
                # SQLite stores Uuid as CHAR(32) hex — the stdlib sqlite3
                # driver can't bind a uuid.UUID object directly, so we
                # produce the hex form ourselves. Using sa.text() bypasses
                # SQLAlchemy's type adapter; values go straight to the
                # DBAPI driver.
                provider_id = uuid.uuid4().hex
                bind.execute(
                    sa.text("""
                        INSERT INTO providers (
                            id, owner_id, practice_name,
                            location_city, location_state, location_zip,
                            in_person_sessions, virtual_sessions,
                            created_at, updated_at
                        ) VALUES (
                            :id, :owner_id, :practice_name,
                            :location_city, :location_state, :location_zip,
                            :in_person_sessions, :virtual_sessions,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        )
                        """),
                    {
                        "id": provider_id,
                        "owner_id": row.owner_id,
                        "practice_name": row.practice_name,
                        "location_city": row.location_city or "(unspecified)",
                        "location_state": row.location_state,
                        "location_zip": row.location_zip or "00000",
                        "in_person_sessions": row.in_person_sessions
                        or "please_contact",
                        "virtual_sessions": row.virtual_sessions or "please_contact",
                    },
                )

            bind.execute(
                sa.text(
                    "UPDATE provider_availability_details "
                    "SET provider_id = :provider_id WHERE post_id = :post_id"
                ),
                {"provider_id": provider_id, "post_id": row.post_id},
            )

    # 3) Now that provider_id is populated everywhere, drop the now-
    # redundant columns and tighten provider_id to NOT NULL + FK. Each
    # operation is gated on whether the prior schema element is still
    # present, so the block is safe to re-run from any partial state.
    existing_checks = _check_constraint_names(bind, _TABLE)
    existing_cols = _column_names(bind, _TABLE)
    existing_fks = _foreign_key_columns(bind, _TABLE)

    with op.batch_alter_table(_TABLE) as batch_op:
        for ck in _OLD_CHECK_CONSTRAINTS:
            if ck in existing_checks:
                batch_op.drop_constraint(ck, type_="check")

        batch_op.alter_column("provider_id", nullable=False)

        if ("provider_id",) not in existing_fks:
            batch_op.create_foreign_key(
                "fk_provider_availability_details_provider_id",
                "providers",
                ["provider_id"],
                ["id"],
                ondelete="CASCADE",
            )

        for col in _OLD_COLUMNS:
            if col in existing_cols:
                batch_op.drop_column(col)


def downgrade() -> None:
    bind = op.get_bind()
    existing_cols = _column_names(bind, _TABLE)

    # Re-add any of the six columns that were dropped on the upgrade.
    cols_to_add = [c for c in _OLD_COLUMNS if c not in existing_cols]
    if cols_to_add:
        with op.batch_alter_table(_TABLE) as batch_op:
            for col in cols_to_add:
                batch_op.add_column(sa.Column(col, sa.TEXT(), nullable=True))

    # Backfill the re-added columns from the linked Provider.
    op.execute("""
        UPDATE provider_availability_details
        SET practice_name = (SELECT practice_name FROM providers WHERE providers.id = provider_availability_details.provider_id),
            location_city = (SELECT location_city FROM providers WHERE providers.id = provider_availability_details.provider_id),
            location_state = (SELECT location_state FROM providers WHERE providers.id = provider_availability_details.provider_id),
            location_zip = (SELECT location_zip FROM providers WHERE providers.id = provider_availability_details.provider_id),
            in_person_sessions = (SELECT in_person_sessions FROM providers WHERE providers.id = provider_availability_details.provider_id),
            virtual_sessions = (SELECT virtual_sessions FROM providers WHERE providers.id = provider_availability_details.provider_id)
        """)

    existing_checks = _check_constraint_names(bind, _TABLE)
    existing_fks = _foreign_key_columns(bind, _TABLE)

    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.alter_column("practice_name", nullable=False)
        batch_op.alter_column("location_state", nullable=False)

        if "ck_provider_availability_details_location_state" not in existing_checks:
            batch_op.create_check_constraint(
                "ck_provider_availability_details_location_state",
                "location_state IN ('AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'DC', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY')",
            )
        if "ck_provider_availability_details_in_person_sessions" not in existing_checks:
            batch_op.create_check_constraint(
                "ck_provider_availability_details_in_person_sessions",
                "in_person_sessions IN ('yes', 'no', 'please_contact')",
            )
        if "ck_provider_availability_details_virtual_sessions" not in existing_checks:
            batch_op.create_check_constraint(
                "ck_provider_availability_details_virtual_sessions",
                "virtual_sessions IN ('yes', 'no', 'please_contact')",
            )

        if ("provider_id",) in existing_fks:
            batch_op.drop_constraint(
                "fk_provider_availability_details_provider_id", type_="foreignkey"
            )
        if "provider_id" in _column_names(bind, _TABLE):
            batch_op.drop_column("provider_id")
