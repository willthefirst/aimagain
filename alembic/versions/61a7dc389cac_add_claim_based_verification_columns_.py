"""add claim-based verification columns (Phase 1a)

Revision ID: 61a7dc389cac
Revises: 4cdc6117dcb8
Create Date: 2026-05-31 12:49:45.519068

Additive columns + CHECK constraints for the two-claim verification model:

- `clinicians`: NPPES Type-1 match cache + Claim A denorm
  (`npi_match_status`, `npi_verified_at`, `clinician_verified`,
  `verified_at`, `ever_verified_at`).
- `organizations`: Type-2 NPI + Claim B prerequisite cache (`npi`,
  `npi_match_status`, `org_verified`, `verified_at`,
  `authorized_official_name`).
- `clinician_licensures`: derived `status` cache + clinician-asserted
  `attested_active`/`attested_at`.

CHECK constraints (`npi_match_status` IN NpiMatchStatus values, license
`status` IN LicenseStatus values, `organizations.npi` 10-digit format)
are added inside `batch_alter_table` blocks so SQLite reissues the table
correctly. Autogenerate doesn't emit CHECKs — they live in the model
`__table_args__` only — so they're added explicitly here.

Pre-launch: no data backfill. New rows default to `none`/`pending`/false.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "61a7dc389cac"
down_revision: Union[str, None] = "4cdc6117dcb8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NPI_MATCH_STATUSES_SQL = (
    "npi_match_status IN ('none', 'pending', 'matched', 'mismatch')"
)
_LICENSE_STATUSES_SQL = "status IN ('active', 'expired', 'pending')"
_ORG_NPI_FORMAT_SQL = (
    "npi IS NULL OR (length(npi) = 10 "
    "AND npi GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]')"
)


def upgrade() -> None:
    with op.batch_alter_table("clinicians") as batch_op:
        batch_op.add_column(
            sa.Column(
                "npi_match_status",
                sa.Text(),
                server_default="none",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("npi_verified_at", sa.TIMESTAMP(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "clinician_verified",
                sa.Boolean(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("verified_at", sa.TIMESTAMP(), nullable=True))
        batch_op.add_column(
            sa.Column("ever_verified_at", sa.TIMESTAMP(), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_clinicians_npi_match_status", _NPI_MATCH_STATUSES_SQL
        )

    with op.batch_alter_table("organizations") as batch_op:
        batch_op.add_column(sa.Column("npi", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "npi_match_status",
                sa.Text(),
                server_default="none",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "org_verified",
                sa.Boolean(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("verified_at", sa.TIMESTAMP(), nullable=True))
        batch_op.add_column(
            sa.Column("authorized_official_name", sa.Text(), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_organizations_npi_match_status", _NPI_MATCH_STATUSES_SQL
        )
        batch_op.create_check_constraint(
            "ck_organizations_npi_format", _ORG_NPI_FORMAT_SQL
        )

    with op.batch_alter_table("clinician_licensures") as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                sa.Text(),
                server_default="pending",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "attested_active",
                sa.Boolean(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("attested_at", sa.TIMESTAMP(), nullable=True))
        batch_op.create_check_constraint(
            "ck_clinician_licensures_status", _LICENSE_STATUSES_SQL
        )


def downgrade() -> None:
    with op.batch_alter_table("clinician_licensures") as batch_op:
        batch_op.drop_constraint("ck_clinician_licensures_status", type_="check")
        batch_op.drop_column("attested_at")
        batch_op.drop_column("attested_active")
        batch_op.drop_column("status")

    with op.batch_alter_table("organizations") as batch_op:
        batch_op.drop_constraint("ck_organizations_npi_format", type_="check")
        batch_op.drop_constraint("ck_organizations_npi_match_status", type_="check")
        batch_op.drop_column("authorized_official_name")
        batch_op.drop_column("verified_at")
        batch_op.drop_column("org_verified")
        batch_op.drop_column("npi_match_status")
        batch_op.drop_column("npi")

    with op.batch_alter_table("clinicians") as batch_op:
        batch_op.drop_constraint("ck_clinicians_npi_match_status", type_="check")
        batch_op.drop_column("ever_verified_at")
        batch_op.drop_column("verified_at")
        batch_op.drop_column("clinician_verified")
        batch_op.drop_column("npi_verified_at")
        batch_op.drop_column("npi_match_status")
