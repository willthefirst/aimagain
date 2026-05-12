"""replace_cr_client_dem_ages_with_age_groups

Revision ID: 5b2d97b1860f
Revises: 9cc643102347
Create Date: 2026-05-11 22:02:30.776513

Sibling to revision `9cc643102347`. CR's `client_dem_ages` was
single-valued; rename + retype to `client_dem_age_groups` JSON list,
mirroring PA's `age_groups` swap. Same `batch_alter_table` SQLite-CHECK
trap documented in `alembic/README.md`.

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b2d97b1860f"
down_revision: Union[str, None] = "9cc643102347"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "client_referral_details",
        sa.Column(
            "client_dem_age_groups",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE client_referral_details "
            "SET client_dem_age_groups = json_array(client_dem_ages)"
        )
    )
    with op.batch_alter_table("client_referral_details") as batch_op:
        batch_op.drop_constraint(
            "ck_client_referral_details_client_dem_ages",
            type_="check",
        )
        batch_op.drop_column("client_dem_ages")


def downgrade() -> None:
    """Downgrade schema.

    Lossy: restore the scalar column from the first list element;
    `client_dem_age_groups[1:]` is discarded.
    """
    op.add_column(
        "client_referral_details",
        sa.Column(
            "client_dem_ages",
            sa.TEXT(),
            server_default=sa.text("'adults_25_64'"),
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE client_referral_details "
            "SET client_dem_ages = json_extract(client_dem_age_groups, '$[0]') "
            "WHERE json_array_length(client_dem_age_groups) > 0"
        )
    )
    with op.batch_alter_table("client_referral_details") as batch_op:
        batch_op.create_check_constraint(
            "ck_client_referral_details_client_dem_ages",
            "client_dem_ages IN ('children_0_5', 'children_6_10', "
            "'preteens_11_13', 'adolescents_14_18', 'young_adults_19_24', "
            "'adults_25_64', 'older_adults_65_plus')",
        )
        batch_op.drop_column("client_dem_age_groups")
