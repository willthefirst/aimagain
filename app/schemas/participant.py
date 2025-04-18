# app/schemas/participant.py
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Literal


# Schema for inviting a user to a conversation
class ParticipantInviteRequest(BaseModel):
    invitee_user_id: str


# Schema for updating participant status
class ParticipantUpdateRequest(BaseModel):
    status: Literal["joined", "rejected"]


# Schema for participant response
class ParticipantResponse(BaseModel):
    id: str
    user_id: str
    conversation_id: str
    status: str
    invited_by_user_id: str | None = None
    initial_message_id: str | None = None
    created_at: datetime
    updated_at: datetime
    joined_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
