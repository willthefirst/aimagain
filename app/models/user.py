import uuid

import sqlalchemy
from fastapi_users.db import SQLAlchemyBaseUserTable
from sqlalchemy import Boolean, Column, ForeignKey, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from .base import BaseModel


# User model inherits from BaseModel and SQLAlchemyBaseUserTable
# Note: SQLAlchemyBaseUserTable requires a specific type for the ID. Uuid works.
class User(SQLAlchemyBaseUserTable[uuid.UUID], BaseModel):
    __tablename__ = "users"

    # id, created_at, updated_at, deleted_at are inherited from BaseModel
    # email, hashed_password, is_active, is_superuser, is_verified are from SQLAlchemyBaseUserTable

    username = Column(
        Text,
        unique=True,
        nullable=False,
        default=lambda: f"user_{uuid.uuid4()}",
    )
    is_online = Column(
        Boolean, nullable=False, server_default=sqlalchemy.sql.expression.false()
    )

    # Relationships
    # Use string forward references for related models to avoid circular imports at module level
    created_conversations = relationship(
        "Conversation",
        back_populates="creator",
        foreign_keys="Conversation.created_by_user_id",  # Simpler reference
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
