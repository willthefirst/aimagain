"""introduce affiliations table; backfill 1 per provider

Second of the coordinated PRs splitting `Provider` (which today
conflates person attributes with practice-role attributes) into a
`Clinician` (person) + `Affiliation` (clinician × org) pair — see
issue #629.

PR 1 (revision ``a1c0b9d2e5f8``) carved out the person side
(`clinicians` table, `npi` moved off `providers`).
PR 2 (this migration) carves out the role side:

  1. Create ``affiliations`` table holding the per-role attributes
     currently on `providers` — `org_id`, `(location_city,
     location_state, location_zip)`, `in_person_sessions`,
     `virtual_sessions`, `accepts_out_of_network`,
     `in_network_carriers`, `sliding_scale`, `cost`. Mirror of the
     columns on `providers`; PR 3 swaps reads onto `affiliations`,
     PR 4 drops the duplicated columns from `providers`.
  2. Add a transitional ``affiliations.provider_id`` UNIQUE FK so PR 3
     can join 1:1 from the legacy `providers` row to its new
     `affiliations` row. UNIQUE because the relationship is still
     1:1 during the transition; PR 4 drops the column (and the
     legacy table) once nothing reads through it.
  3. Add ``affiliations.clinician_id`` (RESTRICT) so the affiliation
     also knows its person — both PR 3's reads and PR 4's
     drop-the-legacy-table step navigate through clinician.
  4. Backfill: one ``affiliations`` row per ``providers`` row,
     copying the per-role columns over with the same created_at /
     updated_at as the source provider. Done in Python so the
     clinician + provider FKs are deterministic.

Out of scope for PR 2:

- No changes to `providers` columns — they stay populated through
  the transition so existing readers don't break.
- Credential sub-table FKs (`provider_licensures.provider_id` etc.)
  also stay — PR 3 moves them to `clinician_id`.

Revision ID: b2d1c4e8f9a3
Revises: a1c0b9d2e5f8
Create Date: 2026-05-19 17:30:00.000000

"""

import uuid

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b2d1c4e8f9a3"
down_revision = "a1c0b9d2e5f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create `affiliations` with the per-role columns mirrored from
    #    `providers` plus the transitional `provider_id` FK.
    op.create_table(
        "affiliations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "provider_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("providers.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "clinician_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("clinicians.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("location_city", sa.Text(), nullable=True),
        sa.Column("location_state", sa.Text(), nullable=True),
        sa.Column("location_zip", sa.Text(), nullable=True),
        sa.Column("in_person_sessions", sa.Text(), nullable=False),
        sa.Column("virtual_sessions", sa.Text(), nullable=False),
        sa.Column(
            "accepts_out_of_network",
            sa.Boolean(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "in_network_carriers",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "sliding_scale",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("cost", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 2. Backfill: one affiliation per provider, copying the per-role
    #    columns and the audit timestamps over.
    bind = op.get_bind()
    providers_meta = sa.Table(
        "providers",
        sa.MetaData(),
        sa.Column("id", sa.Uuid(as_uuid=True)),
        sa.Column("clinician_id", sa.Uuid(as_uuid=True)),
        sa.Column("org_id", sa.Uuid(as_uuid=True)),
        sa.Column("location_city", sa.Text()),
        sa.Column("location_state", sa.Text()),
        sa.Column("location_zip", sa.Text()),
        sa.Column("in_person_sessions", sa.Text()),
        sa.Column("virtual_sessions", sa.Text()),
        sa.Column("accepts_out_of_network", sa.Boolean()),
        sa.Column("in_network_carriers", sa.JSON()),
        sa.Column("sliding_scale", sa.Boolean()),
        sa.Column("cost", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    affiliations_meta = sa.Table(
        "affiliations",
        sa.MetaData(),
        sa.Column("id", sa.Uuid(as_uuid=True)),
        sa.Column("provider_id", sa.Uuid(as_uuid=True)),
        sa.Column("clinician_id", sa.Uuid(as_uuid=True)),
        sa.Column("org_id", sa.Uuid(as_uuid=True)),
        sa.Column("location_city", sa.Text()),
        sa.Column("location_state", sa.Text()),
        sa.Column("location_zip", sa.Text()),
        sa.Column("in_person_sessions", sa.Text()),
        sa.Column("virtual_sessions", sa.Text()),
        sa.Column("accepts_out_of_network", sa.Boolean()),
        sa.Column("in_network_carriers", sa.JSON()),
        sa.Column("sliding_scale", sa.Boolean()),
        sa.Column("cost", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    rows = bind.execute(sa.select(providers_meta)).fetchall()
    for row in rows:
        bind.execute(
            affiliations_meta.insert().values(
                id=uuid.uuid4(),
                provider_id=row.id,
                clinician_id=row.clinician_id,
                org_id=row.org_id,
                location_city=row.location_city,
                location_state=row.location_state,
                location_zip=row.location_zip,
                in_person_sessions=row.in_person_sessions,
                virtual_sessions=row.virtual_sessions,
                accepts_out_of_network=row.accepts_out_of_network,
                in_network_carriers=row.in_network_carriers,
                sliding_scale=row.sliding_scale,
                cost=row.cost,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )


def downgrade() -> None:
    # Drop the table — the per-role columns on `providers` were
    # untouched in the upgrade, so reversal is just removing
    # `affiliations`.
    op.drop_table("affiliations")
