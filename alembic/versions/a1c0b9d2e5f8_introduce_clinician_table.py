"""introduce clinician table; move providers.npi → clinicians.npi

First of the coordinated PRs splitting `Provider` (which today
conflates person attributes with practice-role attributes) into a
`Clinician` (person) + `Affiliation` (clinician × org) pair — see
issue #629.

PR 1 scope (this migration):

  1. Create ``clinicians`` table with the person-attribute column
     currently on ``providers`` — just ``npi`` for now; credential
     sub-tables (licensures, educations, certifications) keep their
     FK to ``providers`` and move in PR 2.
  2. For every existing ``providers`` row, INSERT one ``clinicians``
     row carrying its ``npi``.
  3. Add ``providers.clinician_id`` FK NOT NULL (RESTRICT on delete).
     Backfill from step (2). FK is *not* UNIQUE — PR 2 will attach
     multiple ``providers`` rows (which become ``Affiliation``s) to
     a single ``Clinician`` and we don't want a follow-up migration
     to drop a unique constraint to enable that.
  4. Drop ``providers.npi`` column and its CHECK constraint
     ``ck_providers_npi_format``. The same CHECK is recreated on
     ``clinicians.npi`` as part of step (1).

Templates / routes still read from ``providers``; the surfaced
``npi`` is now sourced via the ``Provider.clinician.npi`` join
(handled in the Pydantic ``ProviderRead`` schema and the
``provider_card_view`` helper).

Dropping a CHECK-constrained column on SQLite requires
``batch_alter_table`` — the unconstrained ``op.drop_column(...)``
fails with `error in table providers after drop column: no such
column: npi`. The batch pattern rewrites the table cleanly.

Revision ID: a1c0b9d2e5f8
Revises: 4a8b2c5d9e1f
Create Date: 2026-05-19 16:00:00.000000

"""

import uuid

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a1c0b9d2e5f8"
down_revision = "4a8b2c5d9e1f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create `clinicians`. The NPI CHECK mirrors the one previously
    #    on `providers.npi` (10 ASCII digits or NULL).
    op.create_table(
        "clinicians",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("npi", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "npi IS NULL OR (length(npi) = 10 "
            "AND npi GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]')",
            name="ck_clinicians_npi_format",
        ),
    )

    # 2. Add `providers.clinician_id` nullable (the FK becomes NOT NULL
    #    after the backfill in step 3). Name the FK explicitly — SQLite
    #    `batch_alter_table` rejects unnamed constraints when it rewrites
    #    the table.
    with op.batch_alter_table("providers") as batch_op:
        batch_op.add_column(
            sa.Column("clinician_id", sa.Uuid(as_uuid=True), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_providers_clinician_id",
            "clinicians",
            ["clinician_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    # 3. Backfill: one clinician per provider, copy the npi over, point
    #    `providers.clinician_id` at the new clinician. Done in Python
    #    so the new clinician ids are deterministic per provider row.
    bind = op.get_bind()
    providers_meta = sa.Table(
        "providers",
        sa.MetaData(),
        sa.Column("id", sa.Uuid(as_uuid=True)),
        sa.Column("npi", sa.Text()),
        sa.Column("clinician_id", sa.Uuid(as_uuid=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
        ),
    )
    clinicians_meta = sa.Table(
        "clinicians",
        sa.MetaData(),
        sa.Column("id", sa.Uuid(as_uuid=True)),
        sa.Column("npi", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
        ),
    )
    rows = bind.execute(
        sa.select(
            providers_meta.c.id,
            providers_meta.c.npi,
            providers_meta.c.created_at,
            providers_meta.c.updated_at,
        )
    ).fetchall()
    for provider_id, npi, created_at, updated_at in rows:
        clinician_id = uuid.uuid4()
        bind.execute(
            clinicians_meta.insert().values(
                id=clinician_id,
                npi=npi,
                created_at=created_at,
                updated_at=updated_at,
            )
        )
        bind.execute(
            providers_meta.update()
            .where(providers_meta.c.id == provider_id)
            .values(clinician_id=clinician_id)
        )

    # 4. Tighten `providers.clinician_id` to NOT NULL and drop the old
    #    `providers.npi` column + its CHECK. SQLite requires
    #    `batch_alter_table` for either operation.
    with op.batch_alter_table("providers") as batch_op:
        batch_op.alter_column("clinician_id", nullable=False)
        batch_op.drop_constraint("ck_providers_npi_format", type_="check")
        batch_op.drop_column("npi")


def downgrade() -> None:
    # Reverse, in order:
    #   1. Re-add `providers.npi` (nullable) and its CHECK.
    #   2. Copy `clinicians.npi` back into the linked `providers.npi`.
    #   3. Drop `providers.clinician_id` (and its FK).
    #   4. Drop `clinicians`.
    with op.batch_alter_table("providers") as batch_op:
        batch_op.add_column(sa.Column("npi", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "ck_providers_npi_format",
            "npi IS NULL OR (length(npi) = 10 "
            "AND npi GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]')",
        )

    bind = op.get_bind()
    providers_meta = sa.Table(
        "providers",
        sa.MetaData(),
        sa.Column("id", sa.Uuid(as_uuid=True)),
        sa.Column("npi", sa.Text()),
        sa.Column("clinician_id", sa.Uuid(as_uuid=True)),
    )
    clinicians_meta = sa.Table(
        "clinicians",
        sa.MetaData(),
        sa.Column("id", sa.Uuid(as_uuid=True)),
        sa.Column("npi", sa.Text()),
    )
    rows = bind.execute(
        sa.select(providers_meta.c.id, providers_meta.c.clinician_id)
    ).fetchall()
    for provider_id, clinician_id in rows:
        if clinician_id is None:
            continue
        clinician = bind.execute(
            sa.select(clinicians_meta.c.npi).where(clinicians_meta.c.id == clinician_id)
        ).first()
        if clinician is None:
            continue
        bind.execute(
            providers_meta.update()
            .where(providers_meta.c.id == provider_id)
            .values(npi=clinician.npi)
        )

    with op.batch_alter_table("providers") as batch_op:
        batch_op.drop_column("clinician_id")

    op.drop_table("clinicians")
