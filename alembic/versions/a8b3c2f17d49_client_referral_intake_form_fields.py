"""client_referral intake form fields

Replaces the placeholder summary/urgency/region columns on `client_referrals`
with the full intake-form schema (Client Location / Demographics /
Description / Services / Insurance — see the form spec in
`templates/posts/new.html`). Existing rows are disposable —
`dev down --volumes` is the recovery path — so the migration drops the old
columns and adds NOT NULL replacements directly.

Revision ID: a8b3c2f17d49
Revises: f3c8e1a47092
Create Date: 2026-05-02 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a8b3c2f17d49"
down_revision: Union[str, None] = "f3c8e1a47092"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def _in_clause(values: tuple[str, ...]) -> str:
    return "'" + "','".join(values) + "'"


def upgrade() -> None:
    """Drop old client_referrals columns, add the intake-form columns."""
    with op.batch_alter_table("client_referrals") as batch_op:
        batch_op.drop_constraint("client_referrals_urgency_check", type_="check")
        batch_op.drop_column("region")
        batch_op.drop_column("urgency")
        batch_op.drop_column("summary")

        # Section 1: Client Location
        batch_op.add_column(sa.Column("location_city", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("location_state", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("location_zip", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("location_in_person", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("location_virtual", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("desired_times", sa.JSON(), nullable=False))

        # Section 2: Demographics
        batch_op.add_column(sa.Column("client_dem_ages", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("language_preferred", sa.Text(), nullable=False))

        # Section 3: Description
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=False))

        # Section 4: Services
        batch_op.add_column(sa.Column("services", sa.JSON(), nullable=False))
        batch_op.add_column(
            sa.Column("services_psychotherapy_modality", sa.Text(), nullable=True)
        )

        # Section 5: Insurance
        batch_op.add_column(sa.Column("insurance", sa.Text(), nullable=False))

        batch_op.create_check_constraint(
            "client_referrals_location_state_check",
            f"location_state IN ({_in_clause(_US_STATES)})",
        )
        batch_op.create_check_constraint(
            "client_referrals_location_in_person_check",
            f"location_in_person IN ({_in_clause(_LOCATION_AVAILABILITY)})",
        )
        batch_op.create_check_constraint(
            "client_referrals_location_virtual_check",
            f"location_virtual IN ({_in_clause(_LOCATION_AVAILABILITY)})",
        )
        batch_op.create_check_constraint(
            "client_referrals_client_dem_ages_check",
            f"client_dem_ages IN ({_in_clause(_AGE_GROUPS)})",
        )
        batch_op.create_check_constraint(
            "client_referrals_language_preferred_check",
            f"language_preferred IN ({_in_clause(_LANGUAGE_PREFERRED)})",
        )
        batch_op.create_check_constraint(
            "client_referrals_insurance_check",
            f"insurance IN ({_in_clause(_INSURANCE)})",
        )


def downgrade() -> None:
    """Reverse upgrade: drop intake-form columns, restore summary/urgency/region."""
    with op.batch_alter_table("client_referrals") as batch_op:
        for constraint in (
            "client_referrals_insurance_check",
            "client_referrals_language_preferred_check",
            "client_referrals_client_dem_ages_check",
            "client_referrals_location_virtual_check",
            "client_referrals_location_in_person_check",
            "client_referrals_location_state_check",
        ):
            batch_op.drop_constraint(constraint, type_="check")

        for column in (
            "insurance",
            "services_psychotherapy_modality",
            "services",
            "description",
            "language_preferred",
            "client_dem_ages",
            "desired_times",
            "location_virtual",
            "location_in_person",
            "location_zip",
            "location_state",
            "location_city",
        ):
            batch_op.drop_column(column)

        batch_op.add_column(sa.Column("summary", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("urgency", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("region", sa.Text(), nullable=False))
        batch_op.create_check_constraint(
            "client_referrals_urgency_check",
            "urgency IN ('low','medium','high')",
        )
