import uuid
from datetime import datetime

from pydantic import BaseModel


# Basic schema for representing a message
class MessageResponse(BaseModel):
    id: uuid.UUID
    content: str
    conversation_id: uuid.UUID
    created_by_user_id: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True
