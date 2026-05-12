"""rename provider_profiles → providers; profile_id → provider_id

Final piece of the provider_profiles → providers rename. The wire URL
(#197), Python internals (#202), and user-scoped path + Pact identifiers
(#203) shipped earlier; this migration aligns the DB schema:

- Renames the parent table `provider_profiles` → `providers`.
- Renames the FK column `profile_id` → `provider_id` on the three
  credential sub-tables (`provider_licensures`, `provider_educations`,
  `provider_certifications`). The sub-table names themselves are already
  `provider_*` (not `provider_profile_*`) and stay.
- Renames the parent's CHECK constraints `ck_provider_profiles_*` →
  `ck_providers_*` so the on-disk names stay in lockstep with `_TABLE`.

Audit-log persisted strings (`audit_log.event_type` rows like
`"create_provider_profile"`, `audit_log.resource_type = "provider_profile"`)
are intentionally **not** migrated — those are immutable historical records
of what the resource was named when the row was written. The Python
identifiers (`AuditAction.CREATE_PROVIDER`, etc.) renamed in #202 already
diverged from these string values; that's the deliberate split.

Revision ID: 9f1a8b2c3d4e
Revises: 8f20a93effc9
Create Date: 2026-05-08

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f1a8b2c3d4e"
down_revision: Union[str, None] = "8f20a93effc9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Verbatim CHECK SQL fragments — copied from 7dbd50c72096 so the rebuilt
# constraints match the original universe exactly. Single source of truth
# for the vocabularies still lives in `src/domain/models/enums.py`; if those tuples
# ever change, follow the standard add-column / new-migration flow rather
# than editing this file.
_IN_PERSON_SESSIONS_CHECK = "in_person_sessions IN ('yes', 'no', 'please_contact')"
_VIRTUAL_SESSIONS_CHECK = "virtual_sessions IN ('yes', 'no', 'please_contact')"
_LOCATION_STATE_CHECK = (
    "location_state IN ('AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'DC', "
    "'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', "
    "'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', "
    "'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', "
    "'VT', 'VA', 'WA', 'WV', 'WI', 'WY')"
)


def upgrade() -> None:
    op.rename_table("provider_profiles", "providers")

    with op.batch_alter_table("providers") as batch_op:
        batch_op.drop_constraint(
            "ck_provider_profiles_in_person_sessions", type_="check"
        )
        batch_op.drop_constraint("ck_provider_profiles_location_state", type_="check")
        batch_op.drop_constraint("ck_provider_profiles_virtual_sessions", type_="check")
        batch_op.create_check_constraint(
            "ck_providers_in_person_sessions", _IN_PERSON_SESSIONS_CHECK
        )
        batch_op.create_check_constraint(
            "ck_providers_location_state", _LOCATION_STATE_CHECK
        )
        batch_op.create_check_constraint(
            "ck_providers_virtual_sessions", _VIRTUAL_SESSIONS_CHECK
        )

    for subtable in (
        "provider_certifications",
        "provider_educations",
        "provider_licensures",
    ):
        with op.batch_alter_table(subtable) as batch_op:
            batch_op.alter_column("profile_id", new_column_name="provider_id")


def downgrade() -> None:
    for subtable in (
        "provider_certifications",
        "provider_educations",
        "provider_licensures",
    ):
        with op.batch_alter_table(subtable) as batch_op:
            batch_op.alter_column("provider_id", new_column_name="profile_id")

    with op.batch_alter_table("providers") as batch_op:
        batch_op.drop_constraint("ck_providers_in_person_sessions", type_="check")
        batch_op.drop_constraint("ck_providers_location_state", type_="check")
        batch_op.drop_constraint("ck_providers_virtual_sessions", type_="check")
        batch_op.create_check_constraint(
            "ck_provider_profiles_in_person_sessions", _IN_PERSON_SESSIONS_CHECK
        )
        batch_op.create_check_constraint(
            "ck_provider_profiles_location_state", _LOCATION_STATE_CHECK
        )
        batch_op.create_check_constraint(
            "ck_provider_profiles_virtual_sessions", _VIRTUAL_SESSIONS_CHECK
        )

    op.rename_table("providers", "provider_profiles")
