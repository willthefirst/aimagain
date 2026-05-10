"""Wire schemas for `UserFavorite` — the user→provider M:N edge.

A favorite is an immutable binary edge: a user either has favorited a
provider or they haven't. The wire surface is therefore minimal — no
Create / Update schemas (POST takes both ids from URL+session; favorites
are never updated). The Read shape powers the favorites listing; the
AuditSnapshot is structurally identical and used for audit before/after.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserFavoriteRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    provider_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserFavoriteAuditSnapshot(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    provider_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
