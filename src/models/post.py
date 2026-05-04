from sqlalchemy import CheckConstraint, Column, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from .base import BaseModel


class Post(BaseModel):
    """Parent row for any post-shaped resource.

    Carries identity, ownership, timestamps, and the `kind` discriminator.
    Kind-specific fields live in a per-kind detail table joined on
    `post_id`. Today the only kind is `'note'` (→ `NoteDetail`); future
    kinds add their own detail tables and widen the CHECK on `kind`.
    """

    __tablename__ = "posts"
    __table_args__ = (CheckConstraint("kind IN ('note')", name="ck_posts_kind"),)

    kind = Column(Text, nullable=False)
    owner_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    owner = relationship("User", lazy="joined")
    note_detail = relationship(
        "NoteDetail",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
