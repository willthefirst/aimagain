"""drop one-profile-per-user uniqueness

Removes `uq_provider_profiles_user_id` so a single user may own multiple
provider profiles. The 1:1 invariant was incorrect for the actual domain:
a user is an account-holder and may own zero, one, or many provider
profiles (e.g. one practitioner with multiple practice contexts, or an
account owner managing distinct practitioners).

The handler-level rejection in `POST /provider-profiles` is removed in
the same change; this migration only touches the DB constraint.

Reverse migration re-adds the constraint, but if 1:N data exists when
downgrade runs the `ALTER TABLE` will fail. Effectively one-way once
multi-profile data lands in production.

Revision ID: 8f20a93effc9
Revises: 7dbd50c72096
Create Date: 2026-05-07 22:03:21.014833

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f20a93effc9"
down_revision: Union[str, None] = "7dbd50c72096"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("provider_profiles") as batch_op:
        batch_op.drop_constraint("uq_provider_profiles_user_id", type_="unique")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("provider_profiles") as batch_op:
        batch_op.create_unique_constraint("uq_provider_profiles_user_id", ["user_id"])
