"""Wire schemas for `UserFavorite` — the user→provider M:N edge.

A favorite is an immutable binary edge: a user either has favorited a
provider or they haven't. The wire surface is therefore minimal — no
Create / Update schemas (POST takes both ids from URL+session; favorites
are never updated). The Read shape powers the favorites listing; the
AuditSnapshot is structurally identical and used for audit before/after.
"""

import uuid
from datetime import datetime

from src.schemas._validators import ReadProjection


class UserFavoriteRead(ReadProjection):
    id: uuid.UUID
    user_id: uuid.UUID
    provider_id: uuid.UUID
    created_at: datetime


class UserFavoriteAuditSnapshot(ReadProjection):
    id: uuid.UUID
    user_id: uuid.UUID
    provider_id: uuid.UUID
    created_at: datetime
