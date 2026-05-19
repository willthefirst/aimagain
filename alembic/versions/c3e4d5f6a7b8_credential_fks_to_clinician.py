"""move credential sub-table FKs from provider_id → clinician_id

First of the #635 cleanup PRs (followup to the #629 epic). The three
provider-credential tables — `provider_licensures`,
`provider_educations`, `provider_certifications` — were FK'd to
`providers.id` for transitional convenience while the #629 split
was in flight. Their content is *person-level* (the same license
follows the clinician across affiliations), so the FK belongs on
`clinicians.id`.

Steps:

  1. Add nullable ``clinician_id`` Uuid column on each sub-table
     with FK to ``clinicians.id`` (CASCADE on delete — the
     credential belongs to the person, so deleting the clinician
     wipes the list).
  2. Backfill: ``UPDATE sub_table SET clinician_id = (SELECT
     clinician_id FROM providers WHERE providers.id =
     sub_table.provider_id)``. Done per-table.
  3. Set ``clinician_id`` NOT NULL.
  4. Drop the legacy ``provider_id`` column + its FK on each
     sub-table. SQLite requires ``batch_alter_table`` for the
     drop.

Out of scope (deferred within #635):

- Dropping the duplicated per-role columns on ``providers`` — PR B.
- Switching the provider create/update handlers to write directly
  to ``affiliations`` — also PR B.
- Renaming Provider → Practice / Listing — separate naming issue.

Revision ID: c3e4d5f6a7b8
Revises: b2d1c4e8f9a3
Create Date: 2026-05-19 17:50:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "c3e4d5f6a7b8"
down_revision = "b2d1c4e8f9a3"
branch_labels = None
depends_on = None


_SUB_TABLES = (
    "provider_licensures",
    "provider_educations",
    "provider_certifications",
)


def upgrade() -> None:
    # 1. Add nullable `clinician_id` to each sub-table.
    for table in _SUB_TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(
                sa.Column("clinician_id", sa.Uuid(as_uuid=True), nullable=True)
            )
            batch_op.create_foreign_key(
                f"fk_{table}_clinician_id",
                "clinicians",
                ["clinician_id"],
                ["id"],
                ondelete="CASCADE",
            )

    # 2. Backfill: copy `provider.clinician_id` to each sub-table row.
    bind = op.get_bind()
    providers_meta = sa.Table(
        "providers",
        sa.MetaData(),
        sa.Column("id", sa.Uuid(as_uuid=True)),
        sa.Column("clinician_id", sa.Uuid(as_uuid=True)),
    )
    for table in _SUB_TABLES:
        sub_meta = sa.Table(
            table,
            sa.MetaData(),
            sa.Column("id", sa.Uuid(as_uuid=True)),
            sa.Column("provider_id", sa.Uuid(as_uuid=True)),
            sa.Column("clinician_id", sa.Uuid(as_uuid=True)),
        )
        rows = bind.execute(sa.select(sub_meta.c.id, sub_meta.c.provider_id)).fetchall()
        for sub_id, provider_id in rows:
            clinician = bind.execute(
                sa.select(providers_meta.c.clinician_id).where(
                    providers_meta.c.id == provider_id
                )
            ).first()
            if clinician is None:
                # Should not happen — every provider has a clinician
                # post-#629 PR 1. Skip rather than crash so a partial
                # database can still upgrade.
                continue
            bind.execute(
                sub_meta.update()
                .where(sub_meta.c.id == sub_id)
                .values(clinician_id=clinician.clinician_id)
            )

    # 3 + 4. Tighten `clinician_id` to NOT NULL and drop the legacy
    # `provider_id` + its FK. SQLite needs `batch_alter_table` for
    # both. The Alembic-default FK name on `provider_id` is
    # `<table>_provider_id_fkey` on Postgres but unnamed on SQLite —
    # `batch_op.drop_column` rewrites the table cleanly and the
    # column drop carries the FK with it.
    for table in _SUB_TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column("clinician_id", nullable=False)
            batch_op.drop_column("provider_id")


def downgrade() -> None:
    # Reverse: re-add `provider_id`, backfill from
    # `clinician_id → providers.clinician_id`, drop `clinician_id`.
    bind = op.get_bind()
    providers_meta = sa.Table(
        "providers",
        sa.MetaData(),
        sa.Column("id", sa.Uuid(as_uuid=True)),
        sa.Column("clinician_id", sa.Uuid(as_uuid=True)),
    )
    for table in _SUB_TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(
                sa.Column("provider_id", sa.Uuid(as_uuid=True), nullable=True)
            )
            batch_op.create_foreign_key(
                f"fk_{table}_provider_id",
                "providers",
                ["provider_id"],
                ["id"],
                ondelete="CASCADE",
            )

        sub_meta = sa.Table(
            table,
            sa.MetaData(),
            sa.Column("id", sa.Uuid(as_uuid=True)),
            sa.Column("provider_id", sa.Uuid(as_uuid=True)),
            sa.Column("clinician_id", sa.Uuid(as_uuid=True)),
        )
        # Pick whichever Provider matches this clinician — there's
        # one in PR-1-era data. The reversed migration can't recover
        # which specific provider a credential belonged to once
        # multiple providers share a clinician (PR-2-future), so the
        # downgrade is best-effort.
        rows = bind.execute(
            sa.select(sub_meta.c.id, sub_meta.c.clinician_id)
        ).fetchall()
        for sub_id, clinician_id in rows:
            provider = bind.execute(
                sa.select(providers_meta.c.id).where(
                    providers_meta.c.clinician_id == clinician_id
                )
            ).first()
            if provider is None:
                continue
            bind.execute(
                sub_meta.update()
                .where(sub_meta.c.id == sub_id)
                .values(provider_id=provider.id)
            )

        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column("provider_id", nullable=False)
            batch_op.drop_column("clinician_id")
