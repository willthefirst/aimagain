"""pa_provider_fk

Revision ID: 537ba27726f9
Revises: 5cecf02ed65d
Create Date: 2026-05-12 16:35:00.000000

#448: provider_availability_details points at a Provider profile via
`provider_id` instead of duplicating practice_name + location +
delivery-format columns. Six columns drop off PA; one FK takes their
place.

Backfill for any existing PA rows: find-or-create a Provider for the
PA's owner matching the row's `practice_name`, then point at it. Match
is on `(owner_id, practice_name)` — duplicates within the same owner
collapse to one Provider; missing locations get filled from the PA row
on the create path. After backfill, NOT NULL is asserted on
`provider_id`, then the six redundant columns drop.

Downgrade re-adds the six columns from the linked Provider's data,
then drops `provider_id`. Lossy on session-format mismatches between
the Provider's posture and the PA row's prior values (those values are
gone; we restore from Provider).

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "537ba27726f9"
down_revision: Union[str, None] = "5cecf02ed65d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Add provider_id as nullable so the table stays valid through
    # the backfill. FK + NOT NULL get tightened at the end.
    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.add_column(
            sa.Column("provider_id", sa.Uuid(), nullable=True),
        )

    bind = op.get_bind()

    # 2) Backfill — for each PA row, find or create a Provider for its
    # owner with matching practice_name. Then set provider_id.
    rows = bind.execute(sa.text("""
            SELECT pad.post_id,
                   p.owner_id,
                   pad.practice_name,
                   pad.location_city,
                   pad.location_state,
                   pad.location_zip,
                   pad.in_person_sessions,
                   pad.virtual_sessions
            FROM provider_availability_details AS pad
            JOIN posts AS p ON p.id = pad.post_id
            """)).fetchall()

    for row in rows:
        post_id = row.post_id
        owner_id = row.owner_id
        practice_name = row.practice_name
        # Look for an existing provider matching owner + practice_name.
        existing = bind.execute(
            sa.text("""
                SELECT id FROM providers
                WHERE owner_id = :owner_id AND practice_name = :practice_name
                LIMIT 1
                """),
            {"owner_id": owner_id, "practice_name": practice_name},
        ).fetchone()
        if existing:
            provider_id = existing.id
        else:
            # Create one. PA's relaxed columns (city/zip/sessions) might
            # be NULL or unset — fill in conservative defaults so the
            # Provider's NOT NULL constraints don't reject the insert.
            import uuid

            provider_id = uuid.uuid4()
            bind.execute(
                sa.text("""
                    INSERT INTO providers (
                        id, owner_id, practice_name,
                        location_city, location_state, location_zip,
                        in_person_sessions, virtual_sessions,
                        created_at, updated_at
                    ) VALUES (
                        :id, :owner_id, :practice_name,
                        :location_city, :location_state, :location_zip,
                        :in_person_sessions, :virtual_sessions,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """),
                {
                    "id": provider_id,
                    "owner_id": owner_id,
                    "practice_name": practice_name,
                    "location_city": row.location_city or "(unspecified)",
                    "location_state": row.location_state,
                    "location_zip": row.location_zip or "00000",
                    "in_person_sessions": row.in_person_sessions or "please_contact",
                    "virtual_sessions": row.virtual_sessions or "please_contact",
                },
            )

        bind.execute(
            sa.text(
                "UPDATE provider_availability_details "
                "SET provider_id = :provider_id WHERE post_id = :post_id"
            ),
            {"provider_id": provider_id, "post_id": post_id},
        )

    # 3) Now that provider_id is populated everywhere, drop the now-
    # redundant columns and tighten provider_id to NOT NULL + FK. The
    # CHECK constraints on the soon-to-be-dropped columns have to come
    # off first, otherwise SQLite's batch table rebuild trips over them.
    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.drop_constraint(
            "ck_provider_availability_details_location_state", type_="check"
        )
        batch_op.drop_constraint(
            "ck_provider_availability_details_in_person_sessions", type_="check"
        )
        batch_op.drop_constraint(
            "ck_provider_availability_details_virtual_sessions", type_="check"
        )
        batch_op.alter_column("provider_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_provider_availability_details_provider_id",
            "providers",
            ["provider_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.drop_column("practice_name")
        batch_op.drop_column("location_city")
        batch_op.drop_column("location_state")
        batch_op.drop_column("location_zip")
        batch_op.drop_column("in_person_sessions")
        batch_op.drop_column("virtual_sessions")


def downgrade() -> None:
    # Re-add the six columns nullable, backfill from the linked
    # Provider, then tighten state to NOT NULL. Drop provider_id last.
    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.add_column(sa.Column("practice_name", sa.TEXT(), nullable=True))
        batch_op.add_column(sa.Column("location_city", sa.TEXT(), nullable=True))
        batch_op.add_column(sa.Column("location_state", sa.TEXT(), nullable=True))
        batch_op.add_column(sa.Column("location_zip", sa.TEXT(), nullable=True))
        batch_op.add_column(sa.Column("in_person_sessions", sa.TEXT(), nullable=True))
        batch_op.add_column(sa.Column("virtual_sessions", sa.TEXT(), nullable=True))

    op.execute("""
        UPDATE provider_availability_details
        SET practice_name = (SELECT practice_name FROM providers WHERE providers.id = provider_availability_details.provider_id),
            location_city = (SELECT location_city FROM providers WHERE providers.id = provider_availability_details.provider_id),
            location_state = (SELECT location_state FROM providers WHERE providers.id = provider_availability_details.provider_id),
            location_zip = (SELECT location_zip FROM providers WHERE providers.id = provider_availability_details.provider_id),
            in_person_sessions = (SELECT in_person_sessions FROM providers WHERE providers.id = provider_availability_details.provider_id),
            virtual_sessions = (SELECT virtual_sessions FROM providers WHERE providers.id = provider_availability_details.provider_id)
        """)

    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.alter_column("practice_name", nullable=False)
        batch_op.alter_column("location_state", nullable=False)
        batch_op.create_check_constraint(
            "ck_provider_availability_details_location_state",
            "location_state IN ('AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'DC', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY')",
        )
        batch_op.create_check_constraint(
            "ck_provider_availability_details_in_person_sessions",
            "in_person_sessions IN ('yes', 'no', 'please_contact')",
        )
        batch_op.create_check_constraint(
            "ck_provider_availability_details_virtual_sessions",
            "virtual_sessions IN ('yes', 'no', 'please_contact')",
        )
        batch_op.drop_constraint(
            "fk_provider_availability_details_provider_id", type_="foreignkey"
        )
        batch_op.drop_column("provider_id")
