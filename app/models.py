import uuid
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
    Enum as SQLAlchemyEnum,
)
from sqlalchemy.orm import relationship, backref, declarative_base, declared_attr
from sqlalchemy.types import Uuid
from fastapi_users.db import SQLAlchemyBaseUserTable
from app.schemas.participant import ParticipantStatus

# Create a Base class for declarative models
# Base = declarative_base() # Remove old Base

# Using TEXT for UUIDs in SQLite, ensuring prefixed IDs are handled by application logic.
# Consider sqlalchemy.Uuid type if using PostgreSQL later.
# --- Refactored to use Uuid type ---


# Define a base model with common fields
class BaseModel(declarative_base()):
    __abstract__ = True  # Make this an abstract base class

    # Use sqlalchemy.types.Uuid for primary key
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    @declared_attr
    def created_at(cls):
        return Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        )

    @declared_attr
    def updated_at(cls):
        return Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        )

    @declared_attr
    def deleted_at(cls):
        return Column(DateTime(timezone=True), nullable=True)


# User model inherits from BaseModel and SQLAlchemyBaseUserTable
# Note: SQLAlchemyBaseUserTable requires a specific type for the ID. Uuid works.
class User(SQLAlchemyBaseUserTable[uuid.UUID], BaseModel):
    __tablename__ = "users"

    # id is inherited from BaseModel
    # id = Column(String, primary_key=True, default=lambda: f"user_{uuid.uuid4()}") # Removed old ID

    username = Column(
        Text,
        unique=True,
        nullable=False,
        default=lambda: f"user_{uuid.uuid4()}",  # Keep username default for now, review later if needed
    )
    # created_at, updated_at, deleted_at inherited from BaseModel
    is_online = Column(
        Boolean, nullable=False, server_default=sqlalchemy.sql.expression.false()
    )

    # Relationships - Foreign keys need type update potentially, but SQLAlchemy handles Uuid mapping
    created_conversations = relationship(
        "Conversation",
        back_populates="creator",
        foreign_keys="[Conversation.created_by_user_id]",
    )
    messages = relationship(
        "Message", back_populates="sender", foreign_keys="[Message.created_by_user_id]"
    )
    participations = relationship(
        "Participant", back_populates="user", foreign_keys="[Participant.user_id]"
    )
    sent_invitations = relationship(
        "Participant",
        back_populates="inviter",
        foreign_keys="[Participant.invited_by_user_id]",
    )


# Conversation model inherits from BaseModel
class Conversation(BaseModel):
    __tablename__ = "conversations"

    # id is inherited from BaseModel
    # id = Column(Text, primary_key=True) # Removed old ID
    name = Column(Text, nullable=True)
    slug = Column(Text, unique=True, nullable=False)  # Keep slug as Text for now
    # Foreign key type updated to Uuid
    created_by_user_id = Column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # created_at, updated_at, deleted_at inherited from BaseModel
    last_activity_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    creator = relationship(
        "User",
        back_populates="created_conversations",
        foreign_keys=[created_by_user_id],
    )
    messages = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan"
    )
    participants = relationship(
        "Participant", back_populates="conversation", cascade="all, delete-orphan"
    )


# Message model inherits from BaseModel
class Message(BaseModel):
    __tablename__ = "messages"

    # id is inherited from BaseModel
    # id = Column(Text, primary_key=True) # Removed old ID
    content = Column(Text, nullable=False)
    # Foreign key types updated to Uuid
    conversation_id = Column(
        Uuid(as_uuid=True), ForeignKey("conversations.id"), nullable=False
    )
    created_by_user_id = Column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # created_at inherited from BaseModel (updated_at, deleted_at not applicable/inherited)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
    sender = relationship(
        "User", back_populates="messages", foreign_keys=[created_by_user_id]
    )  # Specify foreign keys explicitly
    invitations_as_initial = relationship(
        "Participant",
        back_populates="initial_message",
        foreign_keys="[Participant.initial_message_id]",
    )


# Participant model inherits from BaseModel
class Participant(BaseModel):
    __tablename__ = "participants"

    # id is inherited from BaseModel
    # id = Column(Text, primary_key=True) # Removed old ID
    # Foreign key types updated to Uuid
    user_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    conversation_id = Column(
        Uuid(as_uuid=True), ForeignKey("conversations.id"), nullable=False
    )
    # Use SQLAlchemyEnum with the imported ParticipantStatus Enum
    status = Column(SQLAlchemyEnum(ParticipantStatus), nullable=False)
    # Foreign key types updated to Uuid
    invited_by_user_id = Column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    initial_message_id = Column(
        Uuid(as_uuid=True), ForeignKey("messages.id"), nullable=True
    )
    # created_at, updated_at inherited from BaseModel
    joined_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="participations", foreign_keys=[user_id])
    conversation = relationship(
        "Conversation", back_populates="participants", foreign_keys=[conversation_id]
    )  # Specify foreign keys explicitly
    inviter = relationship(
        "User", back_populates="sent_invitations", foreign_keys=[invited_by_user_id]
    )
    initial_message = relationship(
        "Message",
        back_populates="invitations_as_initial",
        foreign_keys=[initial_message_id],
    )

    # Constraints - Remove the status check constraint
    __table_args__ = (
        UniqueConstraint(
            "user_id", "conversation_id", name="uq_participant_user_conversation"
        ),
        # CheckConstraint( # Removed constraint, handled by Enum
        #     "status IN ('invited', 'joined', 'rejected', 'left')",
        #     name="ck_participant_status",
        # ),
    )


# The MetaData object is now associated with the BaseModel's declarative base
metadata = BaseModel.metadata

# We no longer need the separate metadata object from db.py here
# If db.py needs metadata, it should import Base.metadata from this file.
