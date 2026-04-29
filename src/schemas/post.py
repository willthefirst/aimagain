import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PostRead(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
