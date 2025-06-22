from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ConversationCreateRequest(BaseModel):
    invitee_user_id: str
    initial_message: str


class ConversationResponse(BaseModel):
    id: UUID
    created_by_user_id: UUID
    slug: str
    name: str | None = None
    created_at: datetime
    last_activity_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
