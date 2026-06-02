"""add clinician_affiliation_id context to opening_details and referral_details

Revision ID: c4d5e6f7a8b9
Revises: b9c2e1d4f6a8
Create Date: 2026-06-02 00:00:00.000000

A clinician may affiliate with several organizations
(`clinician_affiliations` is 1:N off `clinicians`). This adds the
"context" FK to the two clinician-authored listing kinds — which
affiliation the opening / referral is offered under. Nullable + SET
NULL so removing an affiliation nulls the context rather than blocking.

The backfill seeds every existing row to its clinician's *primary*
affiliation — the earliest by `created_at`, matching
`Clinician.primary_clinician_affiliation` (which returns
`clinician_affiliations[0]` under `order_by=created_at`). Rows whose
clinician has no affiliation, and referral rows with a null
`referring_clinician_id`, stay null.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b9c2e1d4f6a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("opening_details") as batch_op:
        batch_op.add_column(
            sa.Column("clinician_affiliation_id", sa.Uuid(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_opening_details_clinician_affiliation_id",
            "clinician_affiliations",
            ["clinician_affiliation_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("referral_details") as batch_op:
        batch_op.add_column(
            sa.Column("clinician_affiliation_id", sa.Uuid(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_referral_details_clinician_affiliation_id",
            "clinician_affiliations",
            ["clinician_affiliation_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Backfill to each clinician's primary (earliest) affiliation.
    op.execute("""
        UPDATE opening_details
        SET clinician_affiliation_id = (
            SELECT ca.id
            FROM clinician_affiliations ca
            WHERE ca.clinician_id = opening_details.clinician_id
            ORDER BY ca.created_at
            LIMIT 1
        )
        WHERE clinician_id IS NOT NULL
        """)
    op.execute("""
        UPDATE referral_details
        SET clinician_affiliation_id = (
            SELECT ca.id
            FROM clinician_affiliations ca
            WHERE ca.clinician_id = referral_details.referring_clinician_id
            ORDER BY ca.created_at
            LIMIT 1
        )
        WHERE referring_clinician_id IS NOT NULL
        """)


def downgrade() -> None:
    with op.batch_alter_table("referral_details") as batch_op:
        batch_op.drop_constraint(
            "fk_referral_details_clinician_affiliation_id",
            type_="foreignkey",
        )
        batch_op.drop_column("clinician_affiliation_id")

    with op.batch_alter_table("opening_details") as batch_op:
        batch_op.drop_constraint(
            "fk_opening_details_clinician_affiliation_id",
            type_="foreignkey",
        )
        batch_op.drop_column("clinician_affiliation_id")
