"""rename_cr_fields_for_pa_symmetry

Revision ID: 5cecf02ed65d
Revises: 69ff0615ad50
Create Date: 2026-05-12 14:50:00.000000

#450: rename two CR columns for symmetry with PA's already-canonical
names. `client_dem_age_groups` → `age_groups` (the `client_dem_` prefix
was redundant with the `kind` discriminator; CR's sibling `languages`
field already has no such prefix). `services_psychotherapy_modality` →
`treatment_modality` (PA's parallel name; CR's verbose name conflated
"services" with "modality").

Downgrade renames back. No data transform — just column renames.

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5cecf02ed65d"
down_revision: Union[str, None] = "69ff0615ad50"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename both CR columns inside batch_alter_table so SQLite
    rewrites the table once for the pair instead of twice."""
    with op.batch_alter_table("client_referral_details") as batch_op:
        batch_op.alter_column("client_dem_age_groups", new_column_name="age_groups")
        batch_op.alter_column(
            "services_psychotherapy_modality", new_column_name="treatment_modality"
        )


def downgrade() -> None:
    with op.batch_alter_table("client_referral_details") as batch_op:
        batch_op.alter_column("age_groups", new_column_name="client_dem_age_groups")
        batch_op.alter_column(
            "treatment_modality", new_column_name="services_psychotherapy_modality"
        )
