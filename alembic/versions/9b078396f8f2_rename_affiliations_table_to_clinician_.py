"""rename affiliations table to clinician_affiliations

Revision ID: 9b078396f8f2
Revises: 386c191fb144
Create Date: 2026-05-31 18:39:45.972378

Mechanical table rename — `affiliations` becomes `clinician_affiliations`
so the table name pairs symmetrically with the new `org_representations`
table per the two-claim verification model. The class also renamed
(`Affiliation` → `ClinicianAffiliation`); see the matching
src/domain/models/clinician_affiliations/ cluster.

Autogen wanted to drop+create (losing data); using `op.rename_table` +
explicit CHECK-constraint renames preserves rows. Pre-launch the
preservation isn't strictly necessary but rename-in-place is the
cleaner schema-evolution operation.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9b078396f8f2"
down_revision: Union[str, None] = "386c191fb144"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table("affiliations", "clinician_affiliations")
    # Rename the three CHECK constraints to match the new table name so
    # the names stay in lockstep with `named_check_in(_TABLE, ...)`
    # which would generate `ck_clinician_affiliations_*` from now on.
    with op.batch_alter_table("clinician_affiliations") as batch_op:
        batch_op.drop_constraint("ck_affiliations_in_person_sessions", type_="check")
        batch_op.drop_constraint("ck_affiliations_virtual_sessions", type_="check")
        batch_op.drop_constraint("ck_affiliations_location_state", type_="check")
        batch_op.create_check_constraint(
            "ck_clinician_affiliations_in_person_sessions",
            "in_person_sessions IN ('yes', 'no', 'please_contact')",
        )
        batch_op.create_check_constraint(
            "ck_clinician_affiliations_virtual_sessions",
            "virtual_sessions IN ('yes', 'no', 'please_contact')",
        )
        batch_op.create_check_constraint(
            "ck_clinician_affiliations_location_state",
            "location_state IN ('AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', "
            "'DC', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', "
            "'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', "
            "'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', "
            "'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY')",
        )


def downgrade() -> None:
    with op.batch_alter_table("affiliations") as batch_op:
        # The batch op renames the table back to `affiliations` first
        # (via the rename below); these constraint ops then need to use
        # the original names. SQLite batch ops re-create the table
        # under the hood so dropping by current name + recreating with
        # the old names is the safe path.
        pass
    op.rename_table("clinician_affiliations", "affiliations")
    with op.batch_alter_table("affiliations") as batch_op:
        batch_op.drop_constraint(
            "ck_clinician_affiliations_in_person_sessions", type_="check"
        )
        batch_op.drop_constraint(
            "ck_clinician_affiliations_virtual_sessions", type_="check"
        )
        batch_op.drop_constraint(
            "ck_clinician_affiliations_location_state", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_affiliations_in_person_sessions",
            "in_person_sessions IN ('yes', 'no', 'please_contact')",
        )
        batch_op.create_check_constraint(
            "ck_affiliations_virtual_sessions",
            "virtual_sessions IN ('yes', 'no', 'please_contact')",
        )
        batch_op.create_check_constraint(
            "ck_affiliations_location_state",
            "location_state IN ('AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', "
            "'DC', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', "
            "'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', "
            "'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', "
            "'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY')",
        )
