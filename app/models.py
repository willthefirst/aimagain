import sqlalchemy
from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    String,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    func,
)
from sqlalchemy.orm import relationship, backref, declarative_base
from fastapi_users.db import SQLAlchemyBaseUserTableUUID, SQLAlchemyUserDatabase

# Create a Base class for declarative models
Base = declarative_base()

# Using TEXT for UUIDs in SQLite, ensuring prefixed IDs are handled by application logic.
# Consider sqlalchemy.Uuid type if using PostgreSQL later.


class User(SQLAlchemyBaseUserTableUUID, Base):
    __tablename__ = "users"

    id = Column(Text, primary_key=True)  # Renamed from _id
    username = Column(Text, unique=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    is_online = Column(
        Boolean, nullable=False, server_default=sqlalchemy.sql.expression.false()
    )

    # Relationships
    # Conversations created by this user
    created_conversations = relationship(
        "Conversation",
        back_populates="creator",
        foreign_keys="[Conversation.created_by_user_id]",
    )
    # Messages sent by this user
    messages = relationship(
        "Message", back_populates="sender", foreign_keys="[Message.created_by_user_id]"
    )
    # Participants records linking this user to conversations
    participations = relationship(
        "Participant", back_populates="user", foreign_keys="[Participant.user_id]"
    )
    # Invitations sent by this user
    sent_invitations = relationship(
        "Participant",
        back_populates="inviter",
        foreign_keys="[Participant.invited_by_user_id]",
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Text, primary_key=True)  # Renamed from _id
    name = Column(Text, nullable=True)
    slug = Column(Text, unique=True, nullable=False)
    created_by_user_id = Column(
        Text, ForeignKey("users.id"), nullable=False
    )  # Updated FK
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    last_activity_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    # User who created this conversation
    creator = relationship(
        "User",
        back_populates="created_conversations",
        foreign_keys=[created_by_user_id],
    )
    # Messages in this conversation
    messages = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan"
    )
    # Participants in this conversation
    participants = relationship(
        "Participant", back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id = Column(Text, primary_key=True)  # Renamed from _id
    content = Column(Text, nullable=False)
    conversation_id = Column(
        Text, ForeignKey("conversations.id"), nullable=False
    )  # Updated FK
    created_by_user_id = Column(
        Text, ForeignKey("users.id"), nullable=False
    )  # Updated FK
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
    sender = relationship("User", back_populates="messages")
    # Initial message for invitations
    invitations_as_initial = relationship(
        "Participant",
        back_populates="initial_message",
        foreign_keys="[Participant.initial_message_id]",
    )


class Participant(Base):
    __tablename__ = "participants"

    id = Column(Text, primary_key=True)  # Renamed from _id
    user_id = Column(Text, ForeignKey("users.id"), nullable=False)  # Updated FK
    conversation_id = Column(
        Text, ForeignKey("conversations.id"), nullable=False
    )  # Updated FK
    status = Column(Text, nullable=False)  # 'invited', 'joined', 'rejected', 'left'
    invited_by_user_id = Column(
        Text, ForeignKey("users.id"), nullable=True
    )  # Updated FK
    initial_message_id = Column(
        Text, ForeignKey("messages.id"), nullable=True
    )  # Updated FK
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    joined_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="participations", foreign_keys=[user_id])
    conversation = relationship("Conversation", back_populates="participants")
    inviter = relationship(
        "User", back_populates="sent_invitations", foreign_keys=[invited_by_user_id]
    )
    initial_message = relationship(
        "Message",
        back_populates="invitations_as_initial",
        foreign_keys=[initial_message_id],
    )

    # Constraints
    __table_args__ = (
        UniqueConstraint(
            "user_id", "conversation_id", name="uq_participant_user_conversation"
        ),
        CheckConstraint(
            "status IN ('invited', 'joined', 'rejected', 'left')",
            name="ck_participant_status",
        ),
    )


# The MetaData object is now associated with the Base
metadata = Base.metadata

# We no longer need the separate metadata object from db.py here
# If db.py needs metadata, it should import Base.metadata from this file.
