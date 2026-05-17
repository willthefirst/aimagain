"""collapse desired_times slots from morning/afternoon/evening to am/pm

The intake-form `desired_times` grid moves from 7×3 (morning /
afternoon / evening) to 7×2 (am / pm). Stored tokens are remapped:

  - ``*_morning``   → ``*_am``
  - ``*_afternoon`` → ``*_pm``
  - ``*_evening``   → ``*_pm``

The afternoon+evening collapse can produce duplicates within a row's
JSON list; the migration de-duplicates while preserving insertion order
so the rendered grid still matches the user's original selection set.

Downgrade is a one-way information-loss (you can't recover whether a
``*_pm`` originally came from afternoon or evening); we map ``*_am`` →
``*_morning`` and ``*_pm`` → ``*_afternoon`` as the least-surprising
default.

Revision ID: c8e1f04a7b32
Revises: 48cf70d31112
Create Date: 2026-05-17 12:00:00.000000

"""

import json
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8e1f04a7b32"
down_revision: Union[str, None] = "48cf70d31112"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES = ("client_referral_details", "provider_availability_details")

_UPGRADE_MAP = {
    "morning": "am",
    "afternoon": "pm",
    "evening": "pm",
}
_DOWNGRADE_MAP = {
    "am": "morning",
    "pm": "afternoon",
}


def _remap(rows, mapping):
    """Yield (post_id, new_tokens_json) for rows whose tokens changed."""
    for post_id, raw in rows:
        if raw is None:
            continue
        tokens = json.loads(raw) if isinstance(raw, str) else raw
        if not tokens:
            continue
        seen: set[str] = set()
        rewritten: list[str] = []
        for token in tokens:
            if "_" not in token:
                seen.add(token)
                rewritten.append(token)
                continue
            day, _, part = token.rpartition("_")
            new_part = mapping.get(part, part)
            new_token = f"{day}_{new_part}"
            if new_token in seen:
                continue
            seen.add(new_token)
            rewritten.append(new_token)
        if rewritten != tokens:
            yield post_id, json.dumps(rewritten)


def _rewrite(mapping) -> None:
    bind = op.get_bind()
    for table in _TABLES:
        rows = bind.execute(
            sa.text(f"SELECT post_id, desired_times FROM {table}")  # noqa: S608
        ).fetchall()
        for post_id, new_json in _remap(rows, mapping):
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET desired_times = :v WHERE post_id = :pid"  # noqa: S608
                ),
                {"v": new_json, "pid": post_id},
            )


def upgrade() -> None:
    """Upgrade schema."""
    _rewrite(_UPGRADE_MAP)


def downgrade() -> None:
    """Downgrade schema."""
    _rewrite(_DOWNGRADE_MAP)
