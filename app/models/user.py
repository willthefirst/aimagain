import uuid

import sqlalchemy
from fastapi_users.db import SQLAlchemyBaseUserTable
from sqlalchemy import Boolean, Column, Text
from sqlalchemy.orm import relationship

from .base import BaseModel


class User(SQLAlchemyBaseUserTable[uuid.UUID], BaseModel):
    __tablename__ = "users"

    username = Column(
        Text,
        unique=True,
        nullable=False,
        default=lambda: f"user_{uuid.uuid4()}",
    )
    is_online = Column(
        Boolean, nullable=False, server_default=sqlalchemy.sql.expression.false()
    )

    created_conversations = relationship(
        "Conversation",
        back_populates="creator",
        foreign_keys="Conversation.created_by_user_id",
    )
    messages = relationship(
        "Message",
        back_populates="sender",
        foreign_keys="Message.created_by_user_id",
    )
    participations = relationship(
        "Participant",
        back_populates="user",
        foreign_keys="Participant.user_id",
    )
    sent_invitations = relationship(
        "Participant",
        back_populates="inviter",
        foreign_keys="Participant.invited_by_user_id",
    )
