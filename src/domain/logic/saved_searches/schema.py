"""Wire schemas for the `SavedSearch` sub-resource of `User`.

A saved search is `name` + a `filters` dict (the persisted
`filter_values` shape — see `src/domain/models/saved_searches/README.md`
for why the dict is stored structured rather than as a URL string).

`clinician_id`-style owner binding: `user_id` is bound from the URL by
the framework's sub-resource create handler (it appends the new row
through `User.saved_searches`), so it never appears on the wire.

Audit snapshots are byte-identical to :class:`SavedSearchRead`; the
`EntitySpec` defaults `audit_snapshot` to `read_schema`, so this module
declares no separate snapshot class.

Filter-vocabulary validation (rejecting keys that aren't declared
post-filters) is intentionally **not** here yet — PR1 round-trips any
JSON object. The capture/round-trip PR adds validation against the live
`POST_ENTITY.filters` names at the same time it adds the URL helpers
that consume the dict.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from src.framework.schema_validators import (
    PartialUpdate,
    ReadProjection,
    WirePayload,
)


class SavedSearchRead(ReadProjection):
    """Read shape for one SavedSearch row — what the framework's
    create/update routes return and what the audit snapshot mirrors."""

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    filters: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SavedSearchCreate(WirePayload):
    """Create payload. `name` is required; `filters` defaults to the
    empty object (`{}` = "no filters", i.e. the whole directory)."""

    name: str = Field(min_length=1)
    filters: dict[str, Any] = Field(default_factory=dict)


class SavedSearchUpdate(PartialUpdate):
    """Partial update. `None` = leave unchanged; an empty `filters` dict
    (`{}`) clears the filters back to "whole directory"."""

    name: str | None = Field(default=None, min_length=1)
    filters: dict[str, Any] | None = None
