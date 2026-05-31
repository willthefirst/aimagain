"""verification polymorphic refactor (Phase 1b)

Revision ID: 76b43539731b
Revises: 61a7dc389cac
Create Date: 2026-05-31 13:10:03.321049

`verifications` becomes polymorphic across `Clinician` (Claim A,
NPPES Type-1) and `Organization` (Claim B, NPPES Type-2 + authority
events).

Schema delta:
- new `subject_type` discriminator
  (`'clinician'`/`'organization'`, default `'clinician'`)
- new nullable `org_id` FK to `organizations` (CASCADE on delete)
- existing `clinician_id` flipped to nullable
- new `event_type` (default `'npi_resolved'`, CHECK against §9 vocab)
- new `evidence` JSON for NPPES payloads / AO comparisons / admin notes
- new CHECK enforcing exactly one of (`clinician_id`, `org_id`) per
  discriminator value

All ALTERs run inside `batch_alter_table` for SQLite safety (column
nullability flip + adding CHECKs on an existing table). Pre-launch: no
data backfill.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "76b43539731b"
down_revision: Union[str, None] = "61a7dc389cac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SUBJECT_TYPES_SQL = "subject_type IN ('clinician', 'organization')"
_EVENT_TYPES_SQL = (
    "event_type IN ("
    "'npi_submitted', 'npi_resolved', 'license_attested', "
    "'license_expired', 'authority_proven', 'authority_revoked', "
    "'role_set', 'admin_verify', 'admin_suspend', 'email_confirmed'"
    ")"
)
_SUBJECT_SHAPE_SQL = (
    "(subject_type = 'clinician' AND clinician_id IS NOT NULL AND org_id IS NULL) "
    "OR (subject_type = 'organization' "
    "AND clinician_id IS NULL AND org_id IS NOT NULL)"
)


def upgrade() -> None:
    with op.batch_alter_table("verifications") as batch_op:
        batch_op.add_column(
            sa.Column(
                "subject_type",
                sa.Text(),
                server_default="clinician",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("org_id", sa.Uuid(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "event_type",
                sa.Text(),
                server_default="npi_resolved",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("evidence", sa.JSON(), nullable=True))
        batch_op.alter_column("clinician_id", existing_type=sa.Uuid(), nullable=True)
        batch_op.create_index("ix_verifications_org_id", ["org_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_verifications_org_id",
            "organizations",
            ["org_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_check_constraint(
            "ck_verifications_subject_type", _SUBJECT_TYPES_SQL
        )
        batch_op.create_check_constraint(
            "ck_verifications_event_type", _EVENT_TYPES_SQL
        )
        batch_op.create_check_constraint(
            "ck_verifications_subject_shape", _SUBJECT_SHAPE_SQL
        )


def downgrade() -> None:
    with op.batch_alter_table("verifications") as batch_op:
        batch_op.drop_constraint("ck_verifications_subject_shape", type_="check")
        batch_op.drop_constraint("ck_verifications_event_type", type_="check")
        batch_op.drop_constraint("ck_verifications_subject_type", type_="check")
        batch_op.drop_constraint("fk_verifications_org_id", type_="foreignkey")
        batch_op.drop_index("ix_verifications_org_id")
        batch_op.alter_column("clinician_id", existing_type=sa.Uuid(), nullable=False)
        batch_op.drop_column("evidence")
        batch_op.drop_column("event_type")
        batch_op.drop_column("org_id")
        batch_op.drop_column("subject_type")
