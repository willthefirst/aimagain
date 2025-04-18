from pydantic import BaseModel, ConfigDict
from datetime import datetime


# Schema for request body when creating a conversation
class ConversationCreateRequest(BaseModel):
    invitee_user_id: str
    initial_message: str


# Schema for the response when a conversation is created or retrieved
class ConversationResponse(BaseModel):
    id: str
    slug: str
    name: str | None = None
    created_by_user_id: str
    created_at: datetime
    last_activity_at: datetime | None = None

    # Use ConfigDict for Pydantic V2 compatibility
    model_config = ConfigDict(from_attributes=True)


# We might add more schemas later (e.g., for listing, participants)
