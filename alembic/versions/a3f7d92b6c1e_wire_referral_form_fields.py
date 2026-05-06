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
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "DC",
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
)
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


def _check_in_tuple_sql(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(repr(v) for v in values) + ")"


def upgrade() -> None:
    """Upgrade schema."""
    # --- client_referral_details --------------------------------------
    with op.batch_alter_table("client_referral_details") as batch_op:
        # Section 1 — client location
        batch_op.add_column(
            sa.Column("location_city", sa.Text(), server_default="", nullable=False)
        )
        batch_op.add_column(
            sa.Column("location_state", sa.Text(), server_default="AL", nullable=False)
        )
        batch_op.add_column(
            sa.Column("location_zip", sa.Text(), server_default="00000", nullable=False)
        )
        batch_op.add_column(
            sa.Column(
                "location_in_person",
                sa.Text(),
                server_default="no",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "location_virtual",
                sa.Text(),
                server_default="no",
                nullable=False,
            )
        )
        # Section 2 — demographics
        batch_op.add_column(
            sa.Column(
                "client_dem_ages",
                sa.Text(),
                server_default="adults_25_64",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "language_preferred",
                sa.Text(),
                server_default="no",
                nullable=False,
            )
        )
        # Section 4 — services (psychotherapy modality is optional)
        batch_op.add_column(
            sa.Column("services_psychotherapy_modality", sa.Text(), nullable=True)
        )
        # Section 5 — insurance
        batch_op.add_column(
            sa.Column(
                "insurance",
                sa.Text(),
                server_default="in_network",
                nullable=False,
            )
        )

        batch_op.create_check_constraint(
            "ck_client_referral_details_location_state",
            _check_in_tuple_sql("location_state", _US_STATES),
        )
        batch_op.create_check_constraint(
            "ck_client_referral_details_location_in_person",
            _check_in_tuple_sql("location_in_person", _LOCATION_AVAILABILITY),
        )
        batch_op.create_check_constraint(
            "ck_client_referral_details_location_virtual",
            _check_in_tuple_sql("location_virtual", _LOCATION_AVAILABILITY),
        )
        batch_op.create_check_constraint(
            "ck_client_referral_details_client_dem_ages",
            _check_in_tuple_sql("client_dem_ages", _AGE_GROUPS),
        )
        batch_op.create_check_constraint(
            "ck_client_referral_details_language_preferred",
            _check_in_tuple_sql("language_preferred", _LANGUAGE_PREFERRED),
        )
        batch_op.create_check_constraint(
            "ck_client_referral_details_insurance",
            _check_in_tuple_sql("insurance", _INSURANCE),
        )

    # --- provider_availability_details --------------------------------
    with op.batch_alter_table("provider_availability_details") as batch_op:
        # Section 1 — provider information
        batch_op.add_column(
            sa.Column(
                "available_providers",
                sa.Text(),
                server_default="",
                nullable=False,
            )
        )
        # Section 2 — location
        batch_op.add_column(
            sa.Column("location_city", sa.Text(), server_default="", nullable=False)
        )
        batch_op.add_column(
            sa.Column("location_state", sa.Text(), server_default="AL", nullable=False)
        )
        batch_op.add_column(
            sa.Column("location_zip", sa.Text(), server_default="00000", nullable=False)
        )
        # Section 3 — availability
        batch_op.add_column(
            sa.Column(
                "in_person_sessions",
                sa.Text(),
                server_default="no",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "virtual_sessions",
                sa.Text(),
                server_default="no",
                nullable=False,
            )
        )
        # Section 4 — featured services
        batch_op.add_column(sa.Column("treatment_modality", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("client_focus", sa.Text(), server_default="", nullable=False)
        )
        batch_op.add_column(
            sa.Column(
                "age_group",
                sa.Text(),
                server_default="adults_25_64",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "non_english_services",
                sa.Text(),
                server_default="no",
                nullable=False,
            )
        )
        # Section 5 — insurance
        batch_op.add_column(
            sa.Column(
                "payment_situation",
                sa.Text(),
                server_default="in_network",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "sliding_scale",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("cost", sa.Text(), nullable=True))

        batch_op.create_check_constraint(
            "ck_provider_availability_details_location_state",
            _check_in_tuple_sql("location_state", _US_STATES),
        )
        batch_op.create_check_constraint(
            "ck_provider_availability_details_in_person_sessions",
            _check_in_tuple_sql("in_person_sessions", _LOCATION_AVAILABILITY),
        )
        batch_op.create_check_constraint(
            "ck_provider_availability_details_virtual_sessions",
            _check_in_tuple_sql("virtual_sessions", _LOCATION_AVAILABILITY),
        )
        batch_op.create_check_constraint(
            "ck_provider_availability_details_age_group",
            _check_in_tuple_sql("age_group", _AGE_GROUPS),
        )
        batch_op.create_check_constraint(
            "ck_provider_availability_details_non_english_services",
            _check_in_tuple_sql("non_english_services", _LANGUAGE_PREFERRED),
        )
        batch_op.create_check_constraint(
            "ck_provider_availability_details_payment_situation",
            _check_in_tuple_sql("payment_situation", _INSURANCE),
        )


def downgrade() -> None:
    """Downgrade schema."""
    # --- provider_availability_details --------------------------------
    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.drop_constraint(
            "ck_provider_availability_details_payment_situation", type_="check"
        )
        batch_op.drop_constraint(
            "ck_provider_availability_details_non_english_services",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_provider_availability_details_age_group", type_="check"
        )
        batch_op.drop_constraint(
            "ck_provider_availability_details_virtual_sessions", type_="check"
        )
        batch_op.drop_constraint(
            "ck_provider_availability_details_in_person_sessions", type_="check"
        )
        batch_op.drop_constraint(
            "ck_provider_availability_details_location_state", type_="check"
        )

        batch_op.drop_column("cost")
        batch_op.drop_column("sliding_scale")
        batch_op.drop_column("payment_situation")
        batch_op.drop_column("non_english_services")
        batch_op.drop_column("age_group")
        batch_op.drop_column("client_focus")
        batch_op.drop_column("treatment_modality")
        batch_op.drop_column("virtual_sessions")
        batch_op.drop_column("in_person_sessions")
        batch_op.drop_column("location_zip")
        batch_op.drop_column("location_state")
        batch_op.drop_column("location_city")
        batch_op.drop_column("available_providers")

    # --- client_referral_details --------------------------------------
    with op.batch_alter_table("client_referral_details") as batch_op:
        batch_op.drop_constraint("ck_client_referral_details_insurance", type_="check")
        batch_op.drop_constraint(
            "ck_client_referral_details_language_preferred", type_="check"
        )
        batch_op.drop_constraint(
            "ck_client_referral_details_client_dem_ages", type_="check"
        )
        batch_op.drop_constraint(
            "ck_client_referral_details_location_virtual", type_="check"
        )
        batch_op.drop_constraint(
            "ck_client_referral_details_location_in_person", type_="check"
        )
        batch_op.drop_constraint(
            "ck_client_referral_details_location_state", type_="check"
        )

        batch_op.drop_column("insurance")
        batch_op.drop_column("services_psychotherapy_modality")
        batch_op.drop_column("language_preferred")
        batch_op.drop_column("client_dem_ages")
        batch_op.drop_column("location_virtual")
        batch_op.drop_column("location_in_person")
        batch_op.drop_column("location_zip")
        batch_op.drop_column("location_state")
        batch_op.drop_column("location_city")
