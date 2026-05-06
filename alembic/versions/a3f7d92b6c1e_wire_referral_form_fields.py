"""wire client_referral and provider_availability form fields

Extends the per-kind detail tables to cover the scalar (non-multi-select)
fields from `notes/forms_spec.md`. Adds CHECK constraints for the
controlled-vocabulary columns (state, age group, etc.) so the DB-level
universe of accepted values matches the Pydantic `Literal[*TUPLE]`s.

Existing rows from the MVP shape get a sentinel default for each new
NOT NULL column so the SQLite batch-rebuild can fill them in without
violating NOT NULL. Sentinels are picked to satisfy the column's CHECK
(first member of the corresponding enum) or empty/zero where there's no
controlled vocabulary. Wire-layer validation prevents new rows from
being created with sentinel values; the defaults only matter for
backfilling pre-existing MVP test data.

The multi-select fields from the spec (`desired_times`, `services`,
`settings`) follow in a separate migration.

Revision ID: a3f7d92b6c1e
Revises: c2d3e4f5a6b7
Create Date: 2026-05-05 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f7d92b6c1e"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Inlined enum tuples — kept here so this migration is self-contained
# and survives future renames of the model-layer constants. Mirrors the
# tuples in `src/models/post_enums.py` at the time of authoring.
_US_STATES = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
    "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI",
    "WY",
)  # fmt: skip
_LOCATION_AVAILABILITY = ("yes", "no", "please_contact")
_AGE_GROUPS = (
    "children_0_5",
    "children_6_10",
    "preteens_11_13",
    "adolescents_14_18",
    "young_adults_19_24",
    "adults_25_64",
    "older_adults_65_plus",
)
_LANGUAGE_PREFERRED = ("no", "yes")
_INSURANCE = ("in_network", "out_of_network", "in_and_out_of_network")


# --- Tiny file-local helpers --------------------------------------------
#
# Each call site in upgrade()/downgrade() repeats the same shape (text
# column with server default, CHECK constraint named after the table +
# column, paired drops in downgrade). These wrap the boilerplate so the
# migration body reads as a flat field list rather than column-builder
# noise.


def _check_in_tuple_sql(column: str, values: tuple[str, ...]) -> str:
    # SQL single-quote literals with `'` doubled. Mirrors
    # `src.models.post_enums.check_in_tuple_sql`; kept local so the
    # migration stays self-contained.
    quoted = ", ".join("'" + v.replace("'", "''") + "'" for v in values)
    return f"{column} IN ({quoted})"


def _add_required_text(batch_op, column: str, server_default: str = "") -> None:
    batch_op.add_column(
        sa.Column(column, sa.Text(), server_default=server_default, nullable=False)
    )


def _add_optional_text(batch_op, column: str) -> None:
    batch_op.add_column(sa.Column(column, sa.Text(), nullable=True))


def _add_check(batch_op, table: str, column: str, values: tuple[str, ...]) -> None:
    batch_op.create_check_constraint(
        f"ck_{table}_{column}",
        _check_in_tuple_sql(column, values),
    )


def _drop_check(batch_op, table: str, column: str) -> None:
    batch_op.drop_constraint(f"ck_{table}_{column}", type_="check")


def upgrade() -> None:
    """Upgrade schema."""
    # --- client_referral_details --------------------------------------
    table = "client_referral_details"
    with op.batch_alter_table(table) as batch_op:
        # Section 1 — client location
        _add_required_text(batch_op, "location_city")
        _add_required_text(batch_op, "location_state", "AL")
        _add_required_text(batch_op, "location_zip", "00000")
        _add_required_text(batch_op, "location_in_person", "no")
        _add_required_text(batch_op, "location_virtual", "no")
        # Section 2 — demographics
        _add_required_text(batch_op, "client_dem_ages", "adults_25_64")
        _add_required_text(batch_op, "language_preferred", "no")
        # Section 4 — services (psychotherapy modality is optional)
        _add_optional_text(batch_op, "services_psychotherapy_modality")
        # Section 5 — insurance
        _add_required_text(batch_op, "insurance", "in_network")

        _add_check(batch_op, table, "location_state", _US_STATES)
        _add_check(batch_op, table, "location_in_person", _LOCATION_AVAILABILITY)
        _add_check(batch_op, table, "location_virtual", _LOCATION_AVAILABILITY)
        _add_check(batch_op, table, "client_dem_ages", _AGE_GROUPS)
        _add_check(batch_op, table, "language_preferred", _LANGUAGE_PREFERRED)
        _add_check(batch_op, table, "insurance", _INSURANCE)

    # --- provider_availability_details --------------------------------
    table = "provider_availability_details"
    with op.batch_alter_table(table) as batch_op:
        # Section 1 — provider information
        _add_required_text(batch_op, "available_providers")
        # Section 2 — location
        _add_required_text(batch_op, "location_city")
        _add_required_text(batch_op, "location_state", "AL")
        _add_required_text(batch_op, "location_zip", "00000")
        # Section 3 — availability
        _add_required_text(batch_op, "in_person_sessions", "no")
        _add_required_text(batch_op, "virtual_sessions", "no")
        # Section 4 — featured services
        _add_optional_text(batch_op, "treatment_modality")
        _add_required_text(batch_op, "client_focus")
        _add_required_text(batch_op, "age_group", "adults_25_64")
        _add_required_text(batch_op, "non_english_services", "no")
        # Section 5 — insurance
        _add_required_text(batch_op, "payment_situation", "in_network")
        batch_op.add_column(
            sa.Column(
                "sliding_scale",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )
        _add_optional_text(batch_op, "cost")

        _add_check(batch_op, table, "location_state", _US_STATES)
        _add_check(batch_op, table, "in_person_sessions", _LOCATION_AVAILABILITY)
        _add_check(batch_op, table, "virtual_sessions", _LOCATION_AVAILABILITY)
        _add_check(batch_op, table, "age_group", _AGE_GROUPS)
        _add_check(batch_op, table, "non_english_services", _LANGUAGE_PREFERRED)
        _add_check(batch_op, table, "payment_situation", _INSURANCE)


def downgrade() -> None:
    """Downgrade schema."""
    # --- provider_availability_details --------------------------------
    table = "provider_availability_details"
    with op.batch_alter_table(table) as batch_op:
        for column in (
            "payment_situation",
            "non_english_services",
            "age_group",
            "virtual_sessions",
            "in_person_sessions",
            "location_state",
        ):
            _drop_check(batch_op, table, column)

        for column in (
            "cost",
            "sliding_scale",
            "payment_situation",
            "non_english_services",
            "age_group",
            "client_focus",
            "treatment_modality",
            "virtual_sessions",
            "in_person_sessions",
            "location_zip",
            "location_state",
            "location_city",
            "available_providers",
        ):
            batch_op.drop_column(column)

    # --- client_referral_details --------------------------------------
    table = "client_referral_details"
    with op.batch_alter_table(table) as batch_op:
        for column in (
            "insurance",
            "language_preferred",
            "client_dem_ages",
            "location_virtual",
            "location_in_person",
            "location_state",
        ):
            _drop_check(batch_op, table, column)

        for column in (
            "insurance",
            "services_psychotherapy_modality",
            "language_preferred",
            "client_dem_ages",
            "location_virtual",
            "location_in_person",
            "location_zip",
            "location_state",
            "location_city",
        ):
            batch_op.drop_column(column)
