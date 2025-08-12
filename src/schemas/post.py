import enum
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PostType(str, enum.Enum):
    REFERRAL = "referral"
    AVAILABILITY = "availability"


class PostCreateRequest(BaseModel):
    title: str
    content: str
    post_type: PostType


class PostUpdateRequest(BaseModel):
    title: str | None = None
    content: str | None = None


class PostResponse(BaseModel):
    id: UUID
    title: str
    content: str
    post_type: PostType
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
