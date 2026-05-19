"""drop duplicated per-role columns from `providers`

Second of the #635 cleanup PRs (PR B). PR A moved the credential
sub-tables' FK from `providers.id` → `clinicians.id`. This migration
drops the per-role columns that #629 PR 2 duplicated from `providers`
onto the new `affiliations` table — `providers` is now a thin
structural table (`id`, `owner_id`, `clinician_id`, audit
timestamps) and every per-role attribute lives only on `affiliations`.

The transitional `affiliations.provider_id` UNIQUE FK stays for now
— it's the 1:1 link the directory's reads navigate through. The
natural next cleanup (if `providers` ever drops to a view or gets
renamed) is to retarget the link at `clinicians.id` and drop this
column.

Columns dropped from `providers` (with their CHECK constraints —
SQLite needs `batch_alter_table` to rewrite the table):

  * `org_id` (FK to organizations.id, RESTRICT)
  * `location_city`, `location_state` (CHECK
    `ck_providers_location_state` against US_STATES), `location_zip`
  * `in_person_sessions` (CHECK `ck_providers_in_person_sessions`
    against LOCATION_AVAILABILITY_OPTIONS)
  * `virtual_sessions` (CHECK `ck_providers_virtual_sessions`
    against LOCATION_AVAILABILITY_OPTIONS)
  * `accepts_out_of_network`
  * `in_network_carriers`
  * `sliding_scale`
  * `cost`

The downgrade re-adds the columns + CHECKs and backfills each from
the linked `affiliations` row.

Revision ID: d4f7a9b1c6e8
Revises: c3e4d5f6a7b8
Create Date: 2026-05-19 18:30:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "d4f7a9b1c6e8"
down_revision = "c3e4d5f6a7b8"
branch_labels = None
depends_on = None


_LOCATION_AVAILABILITY_OPTIONS = ("yes", "no", "please_contact")

# Mirrors `src.domain.models.enums.US_STATES`. Duplicated rather than
# imported so the migration stays runnable when the source tuple moves /
# renames in a future commit.
_US_STATES = (
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
)


def _in_tuple_sql(column: str, values: tuple[str, ...]) -> str:
    """Render the SQL fragment for `column IN ('a', 'b', ...)` —
    mirrors `src.domain.models.enums.check_in_tuple_sql` but inlined
    so the migration doesn't depend on a domain-layer import."""
    rendered = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({rendered})"


def upgrade() -> None:
    # SQLite needs `batch_alter_table` because the drops affect named
    # CHECK constraints and a foreign key. `batch_alter_table` rewrites
    # the table without the dropped columns; the FK on `org_id` goes
    # with the column, but the named CHECKs survive the column drop
    # (SQLAlchemy reflects them onto the rewritten table) — drop them
    # explicitly so the rewrite doesn't reference the dropped columns.
    with op.batch_alter_table("providers") as batch_op:
        batch_op.drop_constraint("ck_providers_location_state", type_="check")
        batch_op.drop_constraint("ck_providers_in_person_sessions", type_="check")
        batch_op.drop_constraint("ck_providers_virtual_sessions", type_="check")
        batch_op.drop_column("org_id")
        batch_op.drop_column("location_city")
        batch_op.drop_column("location_state")
        batch_op.drop_column("location_zip")
        batch_op.drop_column("in_person_sessions")
        batch_op.drop_column("virtual_sessions")
        batch_op.drop_column("accepts_out_of_network")
        batch_op.drop_column("in_network_carriers")
        batch_op.drop_column("sliding_scale")
        batch_op.drop_column("cost")


def downgrade() -> None:
    # Re-add the columns nullable so the existing rows survive the
    # ALTER, then backfill from the linked `affiliations` row, then
    # tighten to NOT NULL where the original schema demanded it.
    # SQLite needs `batch_alter_table` for the CHECK + FK + nullability
    # adjustments.
    with op.batch_alter_table("providers") as batch_op:
        batch_op.add_column(sa.Column("org_id", sa.Uuid(as_uuid=True), nullable=True))
        batch_op.add_column(sa.Column("location_city", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("location_state", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("location_zip", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("in_person_sessions", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("virtual_sessions", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "accepts_out_of_network",
                sa.Boolean(),
                server_default=sa.text("1"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "in_network_carriers",
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "sliding_scale",
                sa.Boolean(),
                server_default=sa.text("0"),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("cost", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "fk_providers_org_id",
            "organizations",
            ["org_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    # Backfill from affiliations — one row per provider via the 1:1
    # `affiliations.provider_id` link.
    bind = op.get_bind()
    affiliations_meta = sa.Table(
        "affiliations",
        sa.MetaData(),
        sa.Column("provider_id", sa.Uuid(as_uuid=True)),
        sa.Column("org_id", sa.Uuid(as_uuid=True)),
        sa.Column("location_city", sa.Text()),
        sa.Column("location_state", sa.Text()),
        sa.Column("location_zip", sa.Text()),
        sa.Column("in_person_sessions", sa.Text()),
        sa.Column("virtual_sessions", sa.Text()),
        sa.Column("accepts_out_of_network", sa.Boolean()),
        sa.Column("in_network_carriers", sa.JSON()),
        sa.Column("sliding_scale", sa.Boolean()),
        sa.Column("cost", sa.Text()),
    )
    providers_meta = sa.Table(
        "providers",
        sa.MetaData(),
        sa.Column("id", sa.Uuid(as_uuid=True)),
        sa.Column("org_id", sa.Uuid(as_uuid=True)),
        sa.Column("location_city", sa.Text()),
        sa.Column("location_state", sa.Text()),
        sa.Column("location_zip", sa.Text()),
        sa.Column("in_person_sessions", sa.Text()),
        sa.Column("virtual_sessions", sa.Text()),
        sa.Column("accepts_out_of_network", sa.Boolean()),
        sa.Column("in_network_carriers", sa.JSON()),
        sa.Column("sliding_scale", sa.Boolean()),
        sa.Column("cost", sa.Text()),
    )
    rows = bind.execute(sa.select(affiliations_meta)).fetchall()
    for row in rows:
        bind.execute(
            providers_meta.update()
            .where(providers_meta.c.id == row.provider_id)
            .values(
                org_id=row.org_id,
                location_city=row.location_city,
                location_state=row.location_state,
                location_zip=row.location_zip,
                in_person_sessions=row.in_person_sessions,
                virtual_sessions=row.virtual_sessions,
                accepts_out_of_network=row.accepts_out_of_network,
                in_network_carriers=row.in_network_carriers,
                sliding_scale=row.sliding_scale,
                cost=row.cost,
            )
        )

    # Tighten the original NOT NULL columns + re-add the CHECK
    # constraints that lived on `providers` before PR B.
    with op.batch_alter_table("providers") as batch_op:
        batch_op.alter_column("org_id", nullable=False)
        batch_op.alter_column("location_city", nullable=False)
        batch_op.alter_column("location_state", nullable=False)
        batch_op.alter_column("location_zip", nullable=False)
        batch_op.alter_column("in_person_sessions", nullable=False)
        batch_op.alter_column("virtual_sessions", nullable=False)
        batch_op.alter_column("accepts_out_of_network", nullable=False)
        batch_op.alter_column("in_network_carriers", nullable=False)
        batch_op.alter_column("sliding_scale", nullable=False)
        batch_op.create_check_constraint(
            "ck_providers_location_state",
            _in_tuple_sql("location_state", _US_STATES),
        )
        batch_op.create_check_constraint(
            "ck_providers_in_person_sessions",
            _in_tuple_sql("in_person_sessions", _LOCATION_AVAILABILITY_OPTIONS),
        )
        batch_op.create_check_constraint(
            "ck_providers_virtual_sessions",
            _in_tuple_sql("virtual_sessions", _LOCATION_AVAILABILITY_OPTIONS),
        )
