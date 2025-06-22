import enum
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ParticipantStatus(str, enum.Enum):
    INVITED = "invited"
    JOINED = "joined"
    REJECTED = "rejected"
    LEFT = "left"


class ParticipantInviteRequest(BaseModel):
    invitee_user_id: str


class ParticipantUpdateRequest(BaseModel):
    status: ParticipantStatus


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
