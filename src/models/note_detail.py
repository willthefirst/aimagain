from sqlalchemy import Column, ForeignKey, Text
from sqlalchemy.types import Uuid

from .base import Base


class NoteDetail(Base):
    """Per-kind detail row for posts of `kind = 'note'`.

    The parent `Post` row owns identity, ownership, and timestamps; this
    table holds the note-specific fields. `post_id` is both PK and FK,
    enforcing 1:1 with the parent. CASCADE on the FK keeps the detail row
    in lockstep with the parent's lifecycle.
    """

    __tablename__ = "note_details"

    post_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
