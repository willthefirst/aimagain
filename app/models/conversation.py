
from sqlalchemy import Column, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from .base import BaseModel


class Conversation(BaseModel):
    __tablename__ = "conversations"

    # id, created_at, updated_at, deleted_at are inherited from BaseModel
    name = Column(Text, nullable=True)
    slug = Column(Text, unique=True, nullable=False)
    created_by_user_id = Column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    last_activity_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    creator = relationship(
        "User",
        back_populates="created_conversations",
        foreign_keys=[created_by_user_id],  # Keep list for clarity if needed
    )
    messages = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan"
    )
    participants = relationship(
        "Participant", back_populates="conversation", cascade="all, delete-orphan"
    )
