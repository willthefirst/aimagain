from sqlalchemy import Column, DateTime
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.schemas.participant import ParticipantStatus

from .base import BaseModel


class Participant(BaseModel):
    __tablename__ = "participants"

    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    conversation_id = Column(
        Uuid(as_uuid=True), ForeignKey("conversations.id"), nullable=False
    )
    status = Column(SQLAlchemyEnum(ParticipantStatus), nullable=False)
    invited_by_user_id = Column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    initial_message_id = Column(
        Uuid(as_uuid=True), ForeignKey("messages.id"), nullable=True
    )
    joined_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="participations", foreign_keys=[user_id])
    conversation = relationship(
        "Conversation", back_populates="participants", foreign_keys=[conversation_id]
    )
    inviter = relationship(
        "User", back_populates="sent_invitations", foreign_keys=[invited_by_user_id]
    )
    initial_message = relationship(
        "Message",
        back_populates="invitations_as_initial",
        foreign_keys=[initial_message_id],
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "conversation_id", name="uq_participant_user_conversation"
        ),
    )
