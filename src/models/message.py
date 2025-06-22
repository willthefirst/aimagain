from sqlalchemy import Column, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from .base import BaseModel


class Message(BaseModel):
    __tablename__ = "messages"

    content = Column(Text, nullable=False)
    conversation_id = Column(
        Uuid(as_uuid=True), ForeignKey("conversations.id"), nullable=False
    )
    created_by_user_id = Column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    conversation = relationship("Conversation", back_populates="messages")
    sender = relationship(
        "User", back_populates="messages", foreign_keys=[created_by_user_id]
    )
    invitations_as_initial = relationship(
        "Participant",
        back_populates="initial_message",
        foreign_keys="Participant.initial_message_id",
    )
