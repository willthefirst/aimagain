# app/schemas/participant.py
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Literal
import enum
from uuid import UUID


# Define Enum for Participant Status
class ParticipantStatus(str, enum.Enum):
    INVITED = "invited"
    JOINED = "joined"
    REJECTED = "rejected"
    LEFT = "left"


# Schema for inviting a user to a conversation
class ParticipantInviteRequest(BaseModel):
    invitee_user_id: str


# Schema for updating participant status
class ParticipantUpdateRequest(BaseModel):
    status: ParticipantStatus


# Schema for participant response
class ParticipantResponse(BaseModel):
    id: UUID
    user_id: UUID
    conversation_id: UUID
    status: ParticipantStatus
    invited_by_user_id: UUID | None = None
    initial_message_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    joined_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
