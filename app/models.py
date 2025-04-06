import sqlalchemy
from .db import metadata

# Using TEXT for UUIDs in SQLite, ensuring prefixed IDs are handled by application logic.
# Consider sqlalchemy.Uuid type if using PostgreSQL later.

User = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("_id", sqlalchemy.TEXT, primary_key=True), # e.g., "user_uuid..."
    sqlalchemy.Column("username", sqlalchemy.TEXT, unique=True, nullable=False),
    sqlalchemy.Column("created_at", sqlalchemy.TIMESTAMP, nullable=False, server_default=sqlalchemy.func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.TIMESTAMP, nullable=False, server_default=sqlalchemy.func.now(), onupdate=sqlalchemy.func.now()),
    sqlalchemy.Column("deleted_at", sqlalchemy.TIMESTAMP, nullable=True),
    sqlalchemy.Column("is_online", sqlalchemy.BOOLEAN, nullable=False, server_default=sqlalchemy.sql.expression.false()),
)

Conversation = sqlalchemy.Table(
    "conversations",
    metadata,
    sqlalchemy.Column("_id", sqlalchemy.TEXT, primary_key=True), # e.g., "conv_uuid..."
    sqlalchemy.Column("name", sqlalchemy.TEXT, nullable=True),
    sqlalchemy.Column("slug", sqlalchemy.TEXT, unique=True, nullable=False),
    sqlalchemy.Column("created_by_user_id", sqlalchemy.ForeignKey("users._id"), nullable=False),
    sqlalchemy.Column("created_at", sqlalchemy.TIMESTAMP, nullable=False, server_default=sqlalchemy.func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.TIMESTAMP, nullable=False, server_default=sqlalchemy.func.now(), onupdate=sqlalchemy.func.now()),
    sqlalchemy.Column("deleted_at", sqlalchemy.TIMESTAMP, nullable=True),
    sqlalchemy.Column("last_activity_at", sqlalchemy.TIMESTAMP, nullable=True),
)

Message = sqlalchemy.Table(
    "messages",
    metadata,
    sqlalchemy.Column("_id", sqlalchemy.TEXT, primary_key=True), # e.g., "msg_uuid..."
    sqlalchemy.Column("content", sqlalchemy.TEXT, nullable=False),
    sqlalchemy.Column("conversation_id", sqlalchemy.ForeignKey("conversations._id"), nullable=False),
    sqlalchemy.Column("created_by_user_id", sqlalchemy.ForeignKey("users._id"), nullable=False),
    sqlalchemy.Column("created_at", sqlalchemy.TIMESTAMP, nullable=False, server_default=sqlalchemy.func.now()),
    # No updated_at for messages typically
)

Participant = sqlalchemy.Table(
    "participants",
    metadata,
    sqlalchemy.Column("_id", sqlalchemy.TEXT, primary_key=True), # e.g., "part_uuid..."
    sqlalchemy.Column("user_id", sqlalchemy.ForeignKey("users._id"), nullable=False),
    sqlalchemy.Column("conversation_id", sqlalchemy.ForeignKey("conversations._id"), nullable=False),
    sqlalchemy.Column("status", sqlalchemy.TEXT, nullable=False), # 'invited', 'joined', 'rejected', 'left'
    sqlalchemy.Column("invited_by_user_id", sqlalchemy.ForeignKey("users._id"), nullable=True),
    sqlalchemy.Column("initial_message_id", sqlalchemy.ForeignKey("messages._id"), nullable=True),
    sqlalchemy.Column("created_at", sqlalchemy.TIMESTAMP, nullable=False, server_default=sqlalchemy.func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.TIMESTAMP, nullable=False, server_default=sqlalchemy.func.now(), onupdate=sqlalchemy.func.now()),
    sqlalchemy.Column("joined_at", sqlalchemy.TIMESTAMP, nullable=True),
    # Constraints
    sqlalchemy.UniqueConstraint('user_id', 'conversation_id', name='uq_participant_user_conversation'),
    sqlalchemy.CheckConstraint("status IN ('invited', 'joined', 'rejected', 'left')", name='ck_participant_status')
) 