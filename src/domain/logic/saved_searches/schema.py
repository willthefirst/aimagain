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

`filters` accepts either a real JSON object (API/JSON clients) or a
JSON *string* (the "Save this search" hidden form field on the posts
page submits the current `filter_values` serialized) — `_coerce_filters`
normalizes both to a dict. It then **drops keys that aren't currently
declared `/posts` filters**. Dropping (rather than 422-ing) is the
durability contract: when a post filter is renamed or removed, an
existing saved search referencing the old name degrades to "ignore that
dimension" instead of becoming un-loadable. Values are passed through —
the `/posts` route validates them on use.
"""

import json
import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BeforeValidator, Field

from src.framework.schema_validators import (
    PartialUpdate,
    ReadProjection,
    WirePayload,
)


def _declared_post_filter_names() -> frozenset[str]:
    """Names of the filters the `/posts` list currently declares.

    Imported lazily: `POST_ENTITY` construction is unrelated to this
    module, and a top-level import would couple saved-search schema load
    to post-spec load order. Cheap enough to recompute per validate."""
    from src.domain.specs.posts import POST_ENTITY

    return frozenset(f.name for f in POST_ENTITY.declared_filters)


def _coerce_filters(value: Any) -> Any:
    """Normalize a filters payload to a dict scoped to declared post
    filters. Accepts a dict or a JSON-object string; passes `None`
    through (the PATCH "leave unchanged" sentinel)."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("filters must be a JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError("filters must be a JSON object")
    allowed = _declared_post_filter_names()
    return {k: v for k, v in value.items() if k in allowed}


# Shared field type: coerce-and-scope the filter map. Create defaults to
# `{}` (whole directory); Update layers `| None` for "leave unchanged".
FiltersField = Annotated[dict[str, Any], BeforeValidator(_coerce_filters)]


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
    filters: FiltersField = Field(default_factory=dict)


class SavedSearchUpdate(PartialUpdate):
    """Partial update. `None` = leave unchanged; an empty `filters` dict
    (`{}`) clears the filters back to "whole directory"."""

    name: str | None = Field(default=None, min_length=1)
    filters: FiltersField | None = None
