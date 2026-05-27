"""Wire schemas for `UserFavorite` — the user→provider M:N edge.

A favorite is an immutable binary edge: a user either has favorited a
provider or they haven't. The wire surface is therefore minimal — no
Create / Update schemas (POST takes both ids from URL+session; favorites
are never updated), no Read schema (the favorites listing renders ORM
rows directly via the template). The only schema needed is
`UserFavoriteAuditSnapshot`, consumed by `FAVORITE_ENTITY.edge_audit`'s
snapshotter for audit before/after captures.
"""

import uuid
from datetime import datetime

from src.framework.schema_validators import ReadProjection


class UserFavoriteAuditSnapshot(ReadProjection):
    id: uuid.UUID
    user_id: uuid.UUID
    clinician_id: uuid.UUID
    created_at: datetime
